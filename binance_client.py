"""
Wrapper tipis di atas endpoint publik REST Binance (Futures USD-M & Spot).
Semua endpoint di sini tidak butuh API key (public market data).

Referensi endpoint (Binance API docs):
- Futures exchangeInfo : GET /fapi/v1/exchangeInfo
- Futures 24hr ticker   : GET /fapi/v1/ticker/24hr
- Futures mark price    : GET /fapi/v1/premiumIndex        (berisi markPrice, lastFundingRate)
- Futures funding hist  : GET /fapi/v1/fundingRate
- Futures OI sekarang   : GET /fapi/v1/openInterest
- Futures OI historis   : GET /futures/data/openInterestHist
- Futures L/S ratio     : GET /futures/data/globalLongShortAccountRatio
- Futures klines        : GET /fapi/v1/klines
- Spot exchangeInfo     : GET /api/v3/exchangeInfo
- Spot klines           : GET /api/v3/klines
- Spot 24hr ticker      : GET /api/v3/ticker/24hr
"""

import time
import logging
import requests

import config

logger = logging.getLogger("binance_scanner.client")

_session = requests.Session()
_session.headers.update({"User-Agent": "multi-market-scanner/1.0"})


def _get(url, params=None, max_retries=3):
    """GET dengan retry ringan untuk menangani rate-limit / error transient."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = _session.get(url, params=params, timeout=10)
            if resp.status_code == 429 or resp.status_code == 418:
                # Rate limited / IP banned sementara -> tunggu lebih lama lalu retry
                wait = 5 * attempt
                logger.warning(f"Rate limited ({resp.status_code}) on {url}, wait {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            time.sleep(config.REQUEST_DELAY_SEC)
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request gagal ({attempt}/{max_retries}) {url}: {e}")
            time.sleep(1.5 * attempt)
    logger.error(f"Request gagal permanen setelah {max_retries} percobaan: {url}")
    return None


# ── FUTURES ───────────────────────────────────────────────

def get_futures_usdt_symbols():
    """Daftar simbol futures USD-M yang statusnya TRADING dan quote asset USDT."""
    data = _get(f"{config.FUTURES_BASE_URL}/fapi/v1/exchangeInfo")
    if not data:
        return []
    return [
        s["symbol"] for s in data.get("symbols", [])
        if s.get("quoteAsset") == config.QUOTE_ASSET_FILTER
        and s.get("status") == "TRADING"
        and s.get("contractType") == "PERPETUAL"
    ]


def get_futures_premium_index(symbol):
    """Mark price + funding rate saat ini untuk satu simbol."""
    return _get(f"{config.FUTURES_BASE_URL}/fapi/v1/premiumIndex", {"symbol": symbol})


def get_futures_funding_history(symbol, limit=90):
    """Riwayat funding rate (list of dict, terurut lama->baru)."""
    data = _get(
        f"{config.FUTURES_BASE_URL}/fapi/v1/fundingRate",
        {"symbol": symbol, "limit": limit},
    )
    return data or []


def get_futures_open_interest(symbol):
    """Open interest saat ini (dalam kontrak) untuk satu simbol."""
    return _get(f"{config.FUTURES_BASE_URL}/fapi/v1/openInterest", {"symbol": symbol})


def get_futures_oi_history(symbol, period="1h", limit=30):
    """Riwayat open interest (granular), terurut lama->baru."""
    data = _get(
        f"{config.FUTURES_BASE_URL}/futures/data/openInterestHist",
        {"symbol": symbol, "period": period, "limit": limit},
    )
    return data or []


def get_futures_long_short_ratio(symbol, period="1h", limit=90):
    """Global long/short account ratio historis, terurut lama->baru."""
    data = _get(
        f"{config.FUTURES_BASE_URL}/futures/data/globalLongShortAccountRatio",
        {"symbol": symbol, "period": period, "limit": limit},
    )
    return data or []


def get_futures_klines(symbol, interval="1h", limit=48):
    """Klines futures: list of list sesuai spesifikasi Binance kline."""
    data = _get(
        f"{config.FUTURES_BASE_URL}/fapi/v1/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    return data or []


# ── SPOT ──────────────────────────────────────────────────

def get_spot_usdt_symbols():
    """Daftar simbol spot yang statusnya TRADING dan quote asset USDT."""
    data = _get(f"{config.SPOT_BASE_URL}/api/v3/exchangeInfo")
    if not data:
        return []
    return [
        s["symbol"] for s in data.get("symbols", [])
        if s.get("quoteAsset") == config.QUOTE_ASSET_FILTER
        and s.get("status") == "TRADING"
    ]


def get_spot_klines(symbol, interval="1h", limit=48):
    data = _get(
        f"{config.SPOT_BASE_URL}/api/v3/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    return data or []


def get_spot_ticker_price(symbol):
    """Harga terakhir spot untuk satu simbol."""
    data = _get(f"{config.SPOT_BASE_URL}/api/v3/ticker/price", {"symbol": symbol})
    if not data:
        return None
    try:
        return float(data["price"])
    except (KeyError, ValueError, TypeError):
        return None
