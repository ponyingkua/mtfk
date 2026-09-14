"""
Definisi 5 sinyal non-mainstream:

FUTURES:
  1. funding_divergence      - funding rate ekstrem (relatif riwayat simbol itu sendiri)
                                berlawanan arah dengan price action -> crowded trade, rawan squeeze
  2. oi_price_divergence     - OI naik/turun signifikan sementara harga relatif stagnan/berlawanan
                                -> akumulasi/distribusi tersembunyi
  3. lsr_extreme             - long/short account ratio ekstrem + estimasi kerapatan liquidation
                                cluster dari funding & OI -> area rawan squeeze

SPOT:
  4. volume_spike_relative   - volume candle saat ini adalah outlier (z-score) dibanding baseline
                                rolling milik simbol itu sendiri, bukan angka absolut generik
  5. basis_anomaly           - selisih (basis) harga spot vs futures pada simbol yang sama
                                melebar jauh dari kebiasaannya sendiri

Setiap fungsi mengembalikan None jika tidak ada sinyal, atau dict berisi
detail sinyal jika terpicu. Dict inilah yang nanti dipakai notifier.py
untuk membentuk pesan Telegram.
"""

import logging

import config
import binance_client as client
import stats_utils as stats

logger = logging.getLogger("binance_scanner.signals")


def _safe_float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ── 1) FUNDING RATE DIVERGENCE ───────────────────────────

def check_funding_divergence(symbol):
    history = client.get_futures_funding_history(symbol, limit=config.FUNDING_HISTORY_LIMIT)
    if len(history) < 10:
        return None  # riwayat terlalu pendek (simbol baru listing) -> skip, hindari false signal

    rates = [_safe_float(h.get("fundingRate")) for h in history]
    rates = [r for r in rates if r is not None]
    if len(rates) < 10:
        return None

    current_rate = rates[-1]
    past_rates = rates[:-1]

    pct_rank = stats.percentile_rank(current_rate, past_rates)
    if pct_rank is None:
        return None

    # Ambil price change dalam window yang sama (dari funding history pertama ke sekarang)
    # via kline futures, dipakai utk cek arah divergensi.
    klines = client.get_futures_klines(symbol, interval="1h", limit=config.KLINE_LOOKBACK_FOR_OI)
    if len(klines) < 5:
        return None
    price_start = _safe_float(klines[0][4])   # close candle pertama
    price_now = _safe_float(klines[-1][4])    # close candle terakhir
    price_change_pct = stats.pct_change(price_start, price_now)
    if price_change_pct is None:
        return None

    direction = None
    reason = None

    # Funding sangat positif (mayoritas long bayar short) TAPI harga tidak lagi naik / mulai turun
    # -> long crowded, rawan long squeeze
    if pct_rank >= config.FUNDING_PERCENTILE_HIGH and price_change_pct <= 0:
        direction = "SHORT_BIAS"
        reason = (
            f"Funding rate di persentil {pct_rank*100:.0f}% tertinggi riwayatnya sendiri "
            f"({current_rate*100:.4f}%), namun harga {price_change_pct:+.2f}% dalam "
            f"{config.KLINE_LOOKBACK_FOR_OI}h terakhir -> indikasi long crowded / rawan long squeeze."
        )
    # Funding sangat negatif (mayoritas short bayar long) TAPI harga tidak lagi turun / mulai naik
    # -> short crowded, rawan short squeeze
    elif pct_rank <= config.FUNDING_PERCENTILE_LOW and price_change_pct >= 0:
        direction = "LONG_BIAS"
        reason = (
            f"Funding rate di persentil {pct_rank*100:.0f}% terendah riwayatnya sendiri "
            f"({current_rate*100:.4f}%), namun harga {price_change_pct:+.2f}% dalam "
            f"{config.KLINE_LOOKBACK_FOR_OI}h terakhir -> indikasi short crowded / rawan short squeeze."
        )

    if direction is None:
        return None

    return {
        "signal_type": "funding_divergence",
        "symbol": symbol,
        "market": "FUTURES",
        "direction": direction,
        "reason": reason,
        "metrics": {
            "funding_rate_pct": current_rate * 100,
            "funding_percentile": pct_rank,
            "price_change_pct": price_change_pct,
        },
    }


# ── 2) OI + PRICE DIVERGENCE ──────────────────────────────

def check_oi_price_divergence(symbol):
    oi_hist = client.get_futures_oi_history(symbol, period="1h", limit=config.OI_HISTORY_LIMIT)
    if len(oi_hist) < 10:
        return None

    oi_values = [_safe_float(h.get("sumOpenInterest")) for h in oi_hist]
    oi_values = [v for v in oi_values if v is not None]
    if len(oi_values) < 10:
        return None

    oi_change_pct = stats.pct_change(oi_values[0], oi_values[-1])
    if oi_change_pct is None:
        return None

    klines = client.get_futures_klines(symbol, interval="1h", limit=config.KLINE_LOOKBACK_FOR_OI)
    if len(klines) < 10:
        return None
    price_start = _safe_float(klines[0][4])
    price_now = _safe_float(klines[-1][4])
    price_change_pct = stats.pct_change(price_start, price_now)
    if price_change_pct is None:
        return None

    direction = None
    reason = None
    price_is_flat = abs(price_change_pct) < config.PRICE_CHANGE_FLAT_THRESHOLD_PCT

    # OI naik signifikan tapi harga stagnan -> posisi baru dibuka tanpa breakout harga jelas
    # (akumulasi/distribusi tersembunyi, sering mendahului pergerakan besar)
    if oi_change_pct >= config.OI_CHANGE_THRESHOLD_PCT and price_is_flat:
        direction = "WATCH_BREAKOUT"
        reason = (
            f"Open interest naik {oi_change_pct:+.2f}% dalam {config.OI_HISTORY_LIMIT}h "
            f"namun harga relatif stagnan ({price_change_pct:+.2f}%) -> posisi baru terbentuk "
            f"tanpa breakout harga, berpotensi jadi bahan bakar pergerakan besar berikutnya."
        )
    # OI turun signifikan sementara harga naik -> reli tidak didukung posisi baru (short covering
    # atau distribusi oleh smart money), rally bisa rapuh
    elif oi_change_pct <= -config.OI_CHANGE_THRESHOLD_PCT and price_change_pct > 0:
        direction = "CAUTION_LONG"
        reason = (
            f"Open interest turun {oi_change_pct:+.2f}% dalam {config.OI_HISTORY_LIMIT}h "
            f"sementara harga naik {price_change_pct:+.2f}% -> reli kemungkinan besar "
            f"didorong short-covering, bukan posisi long baru; rawan kehabisan momentum."
        )
    # OI turun signifikan sementara harga turun -> longs menyerah / capitulation
    elif oi_change_pct <= -config.OI_CHANGE_THRESHOLD_PCT and price_change_pct < 0:
        direction = "CAPITULATION"
        reason = (
            f"Open interest turun {oi_change_pct:+.2f}% dan harga turun {price_change_pct:+.2f}% "
            f"dalam {config.OI_HISTORY_LIMIT}h -> indikasi capitulation (posisi ditutup paksa), "
            f"sering menandai akhir dari fase penurunan tajam."
        )

    if direction is None:
        return None

    return {
        "signal_type": "oi_price_divergence",
        "symbol": symbol,
        "market": "FUTURES",
        "direction": direction,
        "reason": reason,
        "metrics": {
            "oi_change_pct": oi_change_pct,
            "price_change_pct": price_change_pct,
        },
    }


# ── 3) LONG/SHORT RATIO EXTREME + LIQUIDATION CLUSTER ────

def check_lsr_extreme(symbol):
    lsr_hist = client.get_futures_long_short_ratio(symbol, period="1h", limit=config.LSR_HISTORY_LIMIT)
    if len(lsr_hist) < 10:
        return None

    ratios = [_safe_float(h.get("longShortRatio")) for h in lsr_hist]
    ratios = [r for r in ratios if r is not None]
    if len(ratios) < 10:
        return None

    current_ratio = ratios[-1]
    past_ratios = ratios[:-1]
    pct_rank = stats.percentile_rank(current_ratio, past_ratios)
    if pct_rank is None:
        return None

    direction = None
    if pct_rank >= config.LSR_PERCENTILE_HIGH:
        direction = "SHORT_BIAS"
        crowd_desc = "long"
    elif pct_rank <= config.LSR_PERCENTILE_LOW:
        direction = "LONG_BIAS"
        crowd_desc = "short"
    else:
        return None

    # Estimasi kerapatan liquidation cluster: proxy sederhana dari funding rate saat ini
    # (funding tinggi searah crowd -> leverage yg dipegang crowd besar -> cluster liquidation lebih rapat
    # di dekat harga sekarang). Ini estimasi kasar, bukan data liquidation aktual (Binance tidak expose
    # order liquidation individual secara publik/real-time untuk semua simbol).
    premium = client.get_futures_premium_index(symbol)
    funding_now = _safe_float(premium.get("lastFundingRate")) if premium else None
    cluster_note = ""
    if funding_now is not None:
        leverage_pressure = "tinggi" if abs(funding_now) > 0.0005 else "sedang/rendah"
        cluster_note = (
            f" Funding saat ini {funding_now*100:.4f}% (tekanan leverage {leverage_pressure}) "
            f"-> estimasi cluster liquidation crowd {crowd_desc} relatif {leverage_pressure} "
            f"kerapatannya di dekat harga sekarang."
        )

    reason = (
        f"Long/Short account ratio di persentil {pct_rank*100:.0f}% "
        f"({'tertinggi' if direction == 'SHORT_BIAS' else 'terendah'}) riwayatnya sendiri "
        f"(ratio={current_ratio:.3f}) -> crowd didominasi posisi {crowd_desc}, rawan {crowd_desc} squeeze."
        f"{cluster_note}"
    )

    return {
        "signal_type": "lsr_extreme",
        "symbol": symbol,
        "market": "FUTURES",
        "direction": direction,
        "reason": reason,
        "metrics": {
            "lsr_current": current_ratio,
            "lsr_percentile": pct_rank,
            "funding_rate_pct": (funding_now * 100) if funding_now is not None else None,
        },
    }


# ── 4) VOLUME SPIKE RELATIVE (SPOT) ──────────────────────

def check_volume_spike_relative(symbol):
    klines = client.get_spot_klines(symbol, interval="1h", limit=config.VOLUME_LOOKBACK + 1)
    if len(klines) < 15:
        return None

    volumes = [_safe_float(k[5]) for k in klines]  # index 5 = volume (base asset)
    volumes = [v for v in volumes if v is not None]
    if len(volumes) < 15:
        return None

    current_volume = volumes[-1]
    baseline_volumes = volumes[:-1]

    z = stats.zscore(current_volume, baseline_volumes)
    if z is None or z < config.VOLUME_ZSCORE_THRESHOLD:
        return None

    price_start = _safe_float(klines[0][4])
    price_now = _safe_float(klines[-1][4])
    price_change_pct = stats.pct_change(price_start, price_now)

    baseline_mean = stats.mean(baseline_volumes)
    multiple_of_avg = (current_volume / baseline_mean) if baseline_mean else None

    reason = (
        f"Volume candle 1h saat ini adalah outlier z-score {z:.2f} terhadap baseline "
        f"{config.VOLUME_LOOKBACK} candle terakhir milik simbol ini sendiri"
        + (f" (~{multiple_of_avg:.1f}x rata-rata)" if multiple_of_avg else "")
        + f". Perubahan harga dalam window sama: {price_change_pct:+.2f}%."
        if price_change_pct is not None else
        f"Volume candle 1h saat ini adalah outlier z-score {z:.2f} terhadap baseline sendiri."
    )

    return {
        "signal_type": "volume_spike_relative",
        "symbol": symbol,
        "market": "SPOT",
        "direction": "WATCH",
        "reason": reason,
        "metrics": {
            "volume_zscore": z,
            "volume_multiple_of_avg": multiple_of_avg,
            "price_change_pct": price_change_pct,
        },
    }


# ── 5) SPOT-FUTURES BASIS ANOMALY ────────────────────────

def check_basis_anomaly(symbol):
    """
    Basis = (futures_mark_price - spot_price) / spot_price * 100
    Basis positif besar -> futures premium terhadap spot (bullish crowd di futures)
    Basis negatif besar -> futures diskon terhadap spot (bearish crowd di futures)

    Anomali dideteksi relatif terhadap riwayat basis simbol itu sendiri (bukan angka mutlak generik),
    karena "basis wajar" berbeda-beda tiap koin tergantung funding rate rezim & likuiditas.
    """
    premium = client.get_futures_premium_index(symbol)
    spot_price = client.get_spot_ticker_price(symbol)
    if not premium or spot_price is None:
        return None

    mark_price = _safe_float(premium.get("markPrice"))
    if mark_price is None or spot_price == 0:
        return None

    current_basis_pct = (mark_price - spot_price) / spot_price * 100.0

    # Riwayat basis didekati dari funding rate history sebagai proxy laju basis, TAPI
    # untuk basis aktual historis kita perlu klines futures+spot yang sejajar waktu.
    fut_klines = client.get_futures_klines(symbol, interval="1h", limit=config.BASIS_HISTORY_LIMIT)
    spot_klines = client.get_spot_klines(symbol, interval="1h", limit=config.BASIS_HISTORY_LIMIT)
    if len(fut_klines) < 15 or len(spot_klines) < 15:
        return None

    n = min(len(fut_klines), len(spot_klines))
    fut_klines, spot_klines = fut_klines[-n:], spot_klines[-n:]

    historical_basis = []
    for fk, sk in zip(fut_klines, spot_klines):
        f_close = _safe_float(fk[4])
        s_close = _safe_float(sk[4])
        if f_close is not None and s_close not in (None, 0):
            historical_basis.append((f_close - s_close) / s_close * 100.0)

    if len(historical_basis) < 15:
        return None

    z = stats.zscore(current_basis_pct, historical_basis)
    baseline_mean = stats.mean(historical_basis)
    deviation_from_mean = abs(current_basis_pct - baseline_mean) if baseline_mean is not None else None

    if z is None:
        # stdev riwayat basis ~0 (basis historisnya nyaris tidak pernah bergerak) -> z-score
        # tidak terdefinisi, tapi ini justru berarti riwayatnya sangat stabil, jadi PENYIMPANGAN
        # SEKECIL APAPUN dari mean itu sendiri sudah berarti. Pakai deviation_from_mean sbg fallback,
        # bukan di-skip begitu saja.
        if deviation_from_mean is None or deviation_from_mean < config.MIN_BASIS_PCT_ABS:
            return None
    else:
        if abs(z) < config.BASIS_ZSCORE_THRESHOLD:
            return None

    if abs(current_basis_pct) < config.MIN_BASIS_PCT_ABS:
        return None  # basis-nya sendiri kecil, anomali statistik tapi tidak actionable

    direction = "SHORT_BIAS" if current_basis_pct > 0 else "LONG_BIAS"
    premium_desc = "premium" if current_basis_pct > 0 else "diskon"
    z_desc = f"z-score {z:.2f}" if z is not None else "riwayat basis nyaris konstan (stdev≈0)"

    reason = (
        f"Basis futures-spot saat ini {current_basis_pct:+.3f}% ({premium_desc}), "
        f"{z_desc} terhadap riwayat basis {config.BASIS_HISTORY_LIMIT}h simbol ini sendiri "
        f"-> pelebaran basis tidak wajar, sering mendahului pergerakan besar sebelum retail sadar."
    )

    return {
        "signal_type": "basis_anomaly",
        "symbol": symbol,
        "market": "SPOT+FUTURES",
        "direction": direction,
        "reason": reason,
        "metrics": {
            "basis_pct": current_basis_pct,
            "basis_zscore": z,
        },
    }


# Daftar semua sinyal futures & spot untuk dipanggil scanner utama
FUTURES_SIGNAL_CHECKS = [
    check_funding_divergence,
    check_oi_price_divergence,
    check_lsr_extreme,
]

SPOT_SIGNAL_CHECKS = [
    check_volume_spike_relative,
]

# basis_anomaly butuh data spot + futures sekaligus, dijalankan terpisah di scanner.py
CROSS_MARKET_SIGNAL_CHECKS = [
    check_basis_anomaly,
]
