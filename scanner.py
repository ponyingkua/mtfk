"""
Entry point scanner. Jalankan dengan:

    python3 scanner.py

Scanner ini looping selamanya, tiap SCAN_INTERVAL_SECONDS (default 1 jam):
  1. Ambil semua pair USDT di Futures & Spot
  2. Untuk tiap pair futures -> jalankan 3 sinyal futures
  3. Untuk tiap pair spot    -> jalankan 1 sinyal volume spike
  4. Untuk pair yang ada di KEDUA market (futures & spot dgn simbol sama) -> jalankan basis anomaly
  5. Kirim tiap sinyal yang terpicu ke Telegram (dengan cooldown)

Set env var TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID sebelum menjalankan, atau
edit langsung di config.py.
"""

import sys
import time
import logging
import traceback

import config
import binance_client as client
import signals
import notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scanner.log"),
    ],
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
    logger.info("=== Mulai siklus scan ===")

    futures_symbols = client.get_futures_usdt_symbols()
    spot_symbols = client.get_spot_usdt_symbols()
    logger.info(f"Ditemukan {len(futures_symbols)} pair futures USDT, {len(spot_symbols)} pair spot USDT")

    if not futures_symbols and not spot_symbols:
        logger.error("Tidak dapat mengambil daftar simbol dari Binance (kemungkinan masalah jaringan/API). Lewati siklus ini.")
        return

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

    logger.info(f"Sinyal dikirim ke Telegram: {sent_count} (sisanya di-skip krn cooldown)")
    logger.info("=== Selesai siklus scan ===")


def main():
    logger.info("Binance Multi-Market Scanner dimulai")

    futures_symbols = client.get_futures_usdt_symbols()
    spot_symbols = client.get_spot_usdt_symbols()
    notifier.notify_startup(len(futures_symbols), len(spot_symbols))

    while True:
        cycle_start = time.time()
        try:
            run_one_scan_cycle()
        except Exception:
            error_trace = traceback.format_exc()
            logger.error(f"Error tak terduga di siklus scan:\n{error_trace}")
            notifier.notify_error(error_trace[-500:])  # potong biar tidak kepanjangan di Telegram

        elapsed = time.time() - cycle_start
        sleep_time = max(0, config.SCAN_INTERVAL_SECONDS - elapsed)
        logger.info(f"Siklus selesai dalam {elapsed:.1f}s, tidur {sleep_time:.1f}s sebelum siklus berikutnya")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
