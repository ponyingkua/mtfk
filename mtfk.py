import html
import logging
import math
import os
import sys
import time
import traceback
from typing import Dict, List, Optional, Tuple

import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "GANTI_DENGAN_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "GANTI_DENGAN_CHAT_ID")

SPOT_BASE_URL = "https://data-api.binance.vision"
QUOTE_ASSET_FILTER = "USDT"

REQUEST_DELAY_SEC = 0.12
MAX_SYMBOLS_TO_SCAN = 120
MIN_QUOTE_VOLUME_24H = 2_000_000

TIMEFRAMES = ["15m", "1h", "4h"]
PRIMARY_TF = "1h"

LOOKBACK = 48
MAD_ZSCORE_THRESHOLD = 3.0
RVOL_MIN = 2.8

MIN_PRICE_CHANGE_PCT = 1.2
STRONG_PRICE_CHANGE_PCT = 3.0

MIN_SCORE_TO_SEND = 72
MAX_SIGNALS_PER_RUN = 8

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("mtfk")

_session = requests.Session()
_session.headers.update({"User-Agent": "mtfk-spot-scanner/2.0"})


def _get(url: str, params: dict = None, max_retries: int = 3) -> Optional[dict | list]:
    for attempt in range(1, max_retries + 1):
        try:
            resp = _session.get(url, params=params, timeout=12)
            if resp.status_code == 451:
                logger.error(f"451 geo-block on {url}")
                return None
            if resp.status_code in (429, 418):
                wait = 4 * attempt
                logger.warning(f"Rate limit {resp.status_code}, sleep {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            time.sleep(REQUEST_DELAY_SEC)
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request fail ({attempt}/{max_retries}) {url}: {e}")
            time.sleep(1.2 * attempt)
    return None


def get_top_liquid_symbols() -> List[str]:
    data = _get(f"{SPOT_BASE_URL}/api/v3/ticker/24hr")
    if not data:
        return []

    candidates = []
    for t in data:
        sym = t.get("symbol", "")
        if not sym.endswith(QUOTE_ASSET_FILTER):
            continue
        try:
            qvol = float(t.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue
        if qvol >= MIN_QUOTE_VOLUME_24H:
            candidates.append((sym, qvol))

    candidates.sort(key=lambda x: x[1], reverse=True)
    symbols = [s for s, _ in candidates[:MAX_SYMBOLS_TO_SCAN]]
    logger.info(f"Liquid symbols selected: {len(symbols)}")
    return symbols


def get_klines(symbol: str, interval: str, limit: int = 60) -> List:
    data = _get(
        f"{SPOT_BASE_URL}/api/v3/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    return data or []


def _safe_float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def mad(values: List[float], med: float = None) -> Optional[float]:
    if len(values) < 3:
        return None
    if med is None:
        med = median(values)
    if med is None:
        return None
    deviations = [abs(v - med) for v in values]
    return median(deviations)


def robust_zscore(current: float, historical: List[float]) -> Optional[float]:
    if len(historical) < 10:
        return None
    med = median(historical)
    m = mad(historical, med)
    if med is None or m is None or m == 0:
        return None
    return (current - med) / (m * 1.4826)


def mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def pct_change(old: float, new: float) -> Optional[float]:
    if old in (None, 0):
        return None
    return (new - old) / abs(old) * 100.0


def analyze_tf(symbol: str, interval: str) -> Optional[Dict]:
    klines = get_klines(symbol, interval, limit=LOOKBACK + 2)
    if len(klines) < 20:
        return None

    volumes = []
    closes = []
    opens = []
    highs = []
    lows = []

    for k in klines:
        v = _safe_float(k[5])
        c = _safe_float(k[4])
        o = _safe_float(k[1])
        h = _safe_float(k[2])
        l = _safe_float(k[3])
        if None in (v, c, o, h, l):
            continue
        volumes.append(v)
        closes.append(c)
        opens.append(o)
        highs.append(h)
        lows.append(l)

    if len(volumes) < 20:
        return None

    curr_vol = volumes[-1]
    baseline_vol = volumes[:-1]
    curr_close = closes[-1]
    prev_close = closes[-2]
    curr_open = opens[-1]

    rz = robust_zscore(curr_vol, baseline_vol)
    avg_vol = mean(baseline_vol)
    rvol = (curr_vol / avg_vol) if avg_vol and avg_vol > 0 else None

    price_chg = pct_change(prev_close, curr_close)
    candle_body_pct = abs(curr_close - curr_open) / curr_open * 100 if curr_open else 0
    is_bullish = curr_close > curr_open
    is_bearish = curr_close < curr_open

    recent_ranges = [highs[i] - lows[i] for i in range(-6, -1)]
    avg_range = mean(recent_ranges) if recent_ranges else None
    curr_range = highs[-1] - lows[-1]
    range_expansion = (curr_range / avg_range) if avg_range and avg_range > 0 else None

    look_hi = max(highs[-13:-1]) if len(highs) >= 13 else None
    look_lo = min(lows[-13:-1]) if len(lows) >= 13 else None
    breakout_up = look_hi is not None and curr_close > look_hi
    breakout_dn = look_lo is not None and curr_close < look_lo

    return {
        "interval": interval,
        "rvol": rvol,
        "robust_z": rz,
        "price_change_pct": price_chg,
        "is_bullish": is_bullish,
        "is_bearish": is_bearish,
        "candle_body_pct": candle_body_pct,
        "range_expansion": range_expansion,
        "breakout_up": breakout_up,
        "breakout_dn": breakout_dn,
        "curr_close": curr_close,
    }


def score_signal(tf_results: Dict[str, Dict]) -> Tuple[Optional[Dict], int]:
    if PRIMARY_TF not in tf_results:
        return None, 0

    primary = tf_results[PRIMARY_TF]
    score = 0
    reasons = []

    rz = primary.get("robust_z")
    rvol = primary.get("rvol")
    if rz is None or rvol is None:
        return None, 0

    if rz >= MAD_ZSCORE_THRESHOLD and rvol >= RVOL_MIN:
        vol_score = min(40, 15 + (rz - MAD_ZSCORE_THRESHOLD) * 6 + (rvol - RVOL_MIN) * 3)
        score += vol_score
        reasons.append(f"vol {rvol:.1f}x z{rz:.1f}")
    else:
        return None, 0

    pchg = primary.get("price_change_pct") or 0
    if abs(pchg) < MIN_PRICE_CHANGE_PCT:
        return None, 0

    direction = "LONG" if pchg > 0 else "SHORT"
    price_score = min(25, 10 + abs(pchg) * 2.5)
    if abs(pchg) >= STRONG_PRICE_CHANGE_PCT:
        price_score += 5
    score += price_score
    reasons.append(f"{pchg:+.1f}%")

    if (direction == "LONG" and primary["is_bullish"]) or (direction == "SHORT" and primary["is_bearish"]):
        score += 8
        reasons.append("candle confirm")
    if primary.get("candle_body_pct", 0) > 1.5:
        score += 4

    rexp = primary.get("range_expansion")
    if rexp and rexp >= 1.6:
        score += 6
        reasons.append(f"range×{rexp:.1f}")

    if (direction == "LONG" and primary.get("breakout_up")) or (direction == "SHORT" and primary.get("breakout_dn")):
        score += 10
        reasons.append("breakout")

    confluence = 0
    for tf in ["15m", "4h"]:
        if tf not in tf_results:
            continue
        other = tf_results[tf]
        other_rz = other.get("robust_z") or 0
        other_rvol = other.get("rvol") or 0
        other_pchg = other.get("price_change_pct") or 0

        if other_rz >= 2.2 or other_rvol >= 2.0:
            confluence += 1
            score += 7

        if (direction == "LONG" and other_pchg > 0.4) or (direction == "SHORT" and other_pchg < -0.4):
            confluence += 1
            score += 6

    if confluence >= 2:
        score += 8
        reasons.append(f"MTF×{confluence}")

    score = min(100, int(score))
    if score < MIN_SCORE_TO_SEND:
        return None, score

    signal = {
        "symbol": None,
        "direction": direction,
        "score": score,
        "primary_rvol": rvol,
        "primary_z": rz,
        "price_change_pct": pchg,
        "reasons": reasons,
        "tf_summary": {tf: {
            "rvol": round(res.get("rvol") or 0, 1),
            "z": round(res.get("robust_z") or 0, 1),
            "chg": round(res.get("price_change_pct") or 0, 1),
        } for tf, res in tf_results.items()},
    }
    return signal, score


def scan_symbol(symbol: str) -> Optional[Dict]:
    tf_results = {}
    for tf in TIMEFRAMES:
        res = analyze_tf(symbol, tf)
        if res:
            tf_results[tf] = res
        time.sleep(0.05)

    if len(tf_results) < 2:
        return None

    signal, score = score_signal(tf_results)
    if signal is None:
        return None

    signal["symbol"] = symbol
    return signal


def run_scan(symbols: List[str]) -> List[Dict]:
    triggered = []
    total = len(symbols)
    for i, sym in enumerate(symbols, 1):
        try:
            sig = scan_symbol(sym)
            if sig:
                triggered.append(sig)
                logger.info(f"[{i}/{total}] HIT {sym} score={sig['score']} {sig['direction']}")
            else:
                if i % 20 == 0:
                    logger.info(f"[{i}/{total}] scanned...")
        except Exception:
            logger.error(f"Error {sym}:\n{traceback.format_exc()}")
    triggered.sort(key=lambda x: x["score"], reverse=True)
    return triggered[:MAX_SIGNALS_PER_RUN]


def format_signal(sig: Dict) -> str:
    sym = html.escape(sig["symbol"])
    direction = sig["direction"]
    emoji = "🟢" if direction == "LONG" else "🔴"
    score = sig["score"]
    rvol = sig["primary_rvol"]
    z = sig["primary_z"]
    chg = sig["price_change_pct"]

    line = f"{emoji} <b>{sym}</b> {direction} · score {score}"
    line += f"\n{rvol:.1f}x vol · z{z:.1f} · {chg:+.1f}%"

    tf_parts = []
    for tf in TIMEFRAMES:
        if tf in sig["tf_summary"]:
            t = sig["tf_summary"][tf]
            tf_parts.append(f"{tf}:{t['rvol']}x")
    if tf_parts:
        line += f"\n{' · '.join(tf_parts)}"

    return line


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=12)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        detail = e.response.text if e.response is not None else str(e)
        logger.error(f"Telegram fail: {detail}")
        return False


def notify_signals(signals: List[Dict]):
    if not signals:
        logger.info("Tidak ada sinyal berkualitas yang memenuhi threshold.")
        return

    header = f"⚡ <b>mtfk</b> · {len(signals)} sinyal terbaik"
    send_telegram(header)
    time.sleep(0.3)

    for sig in signals:
        msg = format_signal(sig)
        ok = send_telegram(msg)
        if ok:
            logger.info(f"Sent: {sig['symbol']} score={sig['score']}")
        time.sleep(0.35)


def notify_error(msg: str):
    text = f"⚠️ <b>mtfk error</b>\n<code>{html.escape(msg[:600])}</code>"
    send_telegram(text)


def main():
    logger.info("=== mtfk start ===")
    try:
        symbols = get_top_liquid_symbols()
        if not symbols:
            logger.error("Gagal ambil daftar simbol liquid.")
            notify_error("Gagal ambil daftar simbol liquid dari Binance")
            sys.exit(1)

        logger.info(f"Scanning {len(symbols)} symbols across {TIMEFRAMES} ...")
        signals = run_scan(symbols)

        logger.info(f"Qualified signals: {len(signals)}")
        notify_signals(signals)

        logger.info("=== mtfk selesai ===")
        sys.exit(0)
    except Exception:
        err = traceback.format_exc()
        logger.error(err)
        notify_error(err[-500:])
        sys.exit(1)


if __name__ == "__main__":
    main()
