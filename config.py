"""
Konfigurasi scanner Binance Futures + Spot.
Ubah nilai di sini untuk tuning tanpa menyentuh logic utama.
"""

import os

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "GANTI_DENGAN_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "GANTI_DENGAN_CHAT_ID")

# ── Binance API ───────────────────────────────────────────
FUTURES_BASE_URL = "https://fapi.binance.com"
SPOT_BASE_URL = "https://api.binance.com"

# Jeda antar request (detik) untuk menghindari rate limit Binance.
# Binance futures weight limit umumnya 2400/menit, spot 6000/menit (1200 IP weight/menit utk beberapa endpoint).
# Loop di scanner ini per-simbol, jadi delay kecil sudah cukup aman untuk ratusan simbol.
REQUEST_DELAY_SEC = 0.15

# ── Scan schedule ─────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 60 * 60  # 1 jam

# Hanya scan pair yang berakhiran ini (quote asset)
QUOTE_ASSET_FILTER = "USDT"

# ── Parameter historis untuk hitung persentil / z-score ──────
# Berapa banyak titik data historis funding rate yang diambil per simbol
# untuk menghitung persentil funding saat ini relatif terhadap riwayatnya sendiri.
FUNDING_HISTORY_LIMIT = 90  # funding Binance = tiap 8 jam -> 90 titik ~= 30 hari

# Berapa candle historis untuk hitung OI trend & price trend (dipakai sinyal OI divergence)
OI_HISTORY_LIMIT = 30       # openInterestHist di endpoint futures granular per 5m/15m/30m/1h/... ; kita pakai "1h" -> 30 titik = 30 jam
KLINE_LOOKBACK_FOR_OI = 30  # jumlah candle 1h yang match dengan OI_HISTORY_LIMIT

# Volume z-score: berapa candle historis dipakai utk hitung mean & stdev volume
VOLUME_LOOKBACK = 48        # 48 candle 1h = 2 hari, cukup untuk baseline volume tanpa terlalu berat ke tren mingguan

# ── Threshold sinyal ──────────────────────────────────────

# 1) Funding Rate Divergence
FUNDING_PERCENTILE_HIGH = 0.90   # funding rate saat ini masuk 10% tertinggi dalam riwayatnya sendiri
FUNDING_PERCENTILE_LOW = 0.10    # funding rate saat ini masuk 10% terendah dalam riwayatnya sendiri
FUNDING_DIVERGENCE_PRICE_LOOKBACK_PCT = 0.0  # perubahan harga (%) dalam window yang sama; 0.0 = threshold arah saja (lihat logic)

# 2) OI + Price Divergence
OI_CHANGE_THRESHOLD_PCT = 5.0     # OI berubah minimal sekian % dalam window OI_HISTORY_LIMIT
PRICE_CHANGE_FLAT_THRESHOLD_PCT = 1.5  # harga dianggap "stagnan" jika perubahan absolut < ini (%)

# 3) Long/Short Ratio Extreme + estimasi liquidation cluster
LSR_PERCENTILE_HIGH = 0.90
LSR_PERCENTILE_LOW = 0.10
LSR_HISTORY_LIMIT = 90            # global long/short account ratio, granularity 1h -> 90 titik ~= 3.75 hari

# 4) Volume Spike Relatif (spot)
VOLUME_ZSCORE_THRESHOLD = 2.5     # candle volume dianggap "spike" jika z-score >= ini

# 5) Spot-Futures Basis Anomaly
BASIS_HISTORY_LIMIT = 48          # berapa titik historis basis dipakai utk baseline mean & stdev
BASIS_ZSCORE_THRESHOLD = 2.0      # basis saat ini dianggap anomali jika |z-score| >= ini
MIN_BASIS_PCT_ABS = 0.15          # filter tambahan: basis absolut minimal sekian % (hindari noise di basis yang memang selalu kecil)

# ── Cooldown notifikasi ───────────────────────────────────
# Supaya tidak spam Telegram dengan sinyal yang sama berulang tiap jam,
# satu (simbol, jenis_sinyal, arah) yang sama tidak dikirim ulang dalam N jam.
SIGNAL_COOLDOWN_HOURS = 6
