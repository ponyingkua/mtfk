"""
Entry point scanner -- MODE SINGLE-RUN untuk GitHub Actions.

Jalankan dengan:

    python3 scanner.py

Script ini menjalankan SATU siklus scan lalu keluar (exit 0 sukses / exit 1 gagal).
Dipicu berulang oleh GitHub Actions cron (lihat .github/workflows/scanner.yml),
BUKAN proses looping/daemon -- karena tiap run GitHub Actions memang mulai dari
container baru yang bersih (tidak ada memori antar run), jadi tidak ada cooldown
antar-run: tiap sinyal yang terpicu pada satu run akan selalu dikirim ke Telegram
pada run itu, meski simbol/jenis sinyalnya sama dengan run sebelumnya.

Alur satu siklus:
  1. Ambil semua pair USDT di Futures & Spot
  2. Untuk tiap pair futures -> jalankan 3 sinyal futures
  3. Untuk tiap pair spot    -> jalankan 1 sinyal volume spike
  4. Untuk pair yang ada di KEDUA market (futures & spot dgn simbol sama) -> jalankan basis anomaly
  5. Kirim tiap sinyal yang terpicu ke Telegram

Env var TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID wajib di-set (lewat GitHub Secrets
saat dijalankan di Actions, atau manual di terminal untuk test lokal).
"""

import sys
import logging
import traceback

import config
import binance_client as client
import signals
import notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],  # cukup stdout -- GitHub Actions sudah menyimpan log run
)
logger = logging.getLogger("binance_scanner.main")


def run_futures_scan(futures_symbols):
    triggered = []
    for symbol in futures_symbols:
        for check_fn in signals.FUTURES_SIGNAL_CHECKS:
            try:
                result = check_fn(symbol)
                if result:
                    triggered.append(result)
            except Exception:
                logger.error(f"Error saat cek {check_fn.__name__} untuk {symbol}:\n{traceback.format_exc()}")
    return triggered


def run_spot_scan(spot_symbols):
    triggered = []
    for symbol in spot_symbols:
        for check_fn in signals.SPOT_SIGNAL_CHECKS:
            try:
                result = check_fn(symbol)
                if result:
                    triggered.append(result)
            except Exception:
                logger.error(f"Error saat cek {check_fn.__name__} untuk {symbol}:\n{traceback.format_exc()}")
    return triggered


def run_cross_market_scan(common_symbols):
    triggered = []
    for symbol in common_symbols:
        for check_fn in signals.CROSS_MARKET_SIGNAL_CHECKS:
            try:
                result = check_fn(symbol)
                if result:
                    triggered.append(result)
            except Exception:
                logger.error(f"Error saat cek {check_fn.__name__} untuk {symbol}:\n{traceback.format_exc()}")
    return triggered


def run_one_scan_cycle():
    """Mengembalikan True jika siklus berhasil dijalankan (walau 0 sinyal), False jika gagal total."""
    logger.info("=== Mulai siklus scan ===")

    futures_symbols = client.get_futures_usdt_symbols()
    spot_symbols = client.get_spot_usdt_symbols()
    logger.info(f"Ditemukan {len(futures_symbols)} pair futures USDT, {len(spot_symbols)} pair spot USDT")

    if not futures_symbols and not spot_symbols:
        logger.error("Tidak dapat mengambil daftar simbol dari Binance (kemungkinan masalah jaringan/API).")
        return False

    all_triggered = []

    logger.info("Scanning futures signals...")
    all_triggered += run_futures_scan(futures_symbols)

    logger.info("Scanning spot signals...")
    all_triggered += run_spot_scan(spot_symbols)

    common_symbols = sorted(set(futures_symbols) & set(spot_symbols))
    logger.info(f"Scanning basis anomaly untuk {len(common_symbols)} simbol yang ada di futures & spot...")
    all_triggered += run_cross_market_scan(common_symbols)

    logger.info(f"Total sinyal terpicu siklus ini: {len(all_triggered)}")

    sent_count = 0
    for sig in all_triggered:
        if notifier.notify_signal(sig):
            sent_count += 1

    logger.info(f"Sinyal dikirim ke Telegram: {sent_count}")
    logger.info("=== Selesai siklus scan ===")
    return True


def main():
    logger.info("Binance Multi-Market Scanner (single-run) dimulai")
    try:
        success = run_one_scan_cycle()
    except Exception:
        error_trace = traceback.format_exc()
        logger.error(f"Error tak terduga di siklus scan:\n{error_trace}")
        notifier.notify_error(error_trace[-500:])  # potong biar tidak kepanjangan di Telegram
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
