"""
Kirim notifikasi sinyal ke Telegram, dengan cooldown supaya sinyal
(symbol, signal_type, direction) yang sama tidak spam tiap jam.
"""

import time
import logging
import requests

import config

logger = logging.getLogger("binance_scanner.notifier")

# cooldown_state: { (symbol, signal_type, direction): last_sent_unix_timestamp }
_cooldown_state = {}

_SIGNAL_LABELS = {
    "funding_divergence": "Funding Rate Divergence",
    "oi_price_divergence": "OI + Price Divergence",
    "lsr_extreme": "Long/Short Ratio Extreme",
    "volume_spike_relative": "Volume Spike (Relatif)",
    "basis_anomaly": "Spot-Futures Basis Anomaly",
}

_DIRECTION_EMOJI = {
    "SHORT_BIAS": "🔴",
    "LONG_BIAS": "🟢",
    "WATCH_BREAKOUT": "🟡",
    "CAUTION_LONG": "🟠",
    "CAPITULATION": "⚪",
    "WATCH": "🔵",
}


def _is_in_cooldown(key):
    last_sent = _cooldown_state.get(key)
    if last_sent is None:
        return False
    elapsed_hours = (time.time() - last_sent) / 3600.0
    return elapsed_hours < config.SIGNAL_COOLDOWN_HOURS


def _mark_sent(key):
    _cooldown_state[key] = time.time()


def format_signal_message(signal):
    label = _SIGNAL_LABELS.get(signal["signal_type"], signal["signal_type"])
    emoji = _DIRECTION_EMOJI.get(signal["direction"], "⚡")

    lines = [
        f"{emoji} <b>{label}</b>",
        f"Simbol: <b>{signal['symbol']}</b> ({signal['market']})",
        f"Arah: <b>{signal['direction']}</b>",
        "",
        signal["reason"],
    ]
    return "\n".join(lines)


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal kirim pesan Telegram: {e}")
        return False


def notify_signal(signal):
    """
    Kirim satu sinyal ke Telegram jika belum dalam masa cooldown.
    Mengembalikan True jika benar-benar dikirim, False jika di-skip (cooldown) atau gagal.
    """
    key = (signal["symbol"], signal["signal_type"], signal["direction"])
    if _is_in_cooldown(key):
        logger.info(f"Skip (cooldown): {key}")
        return False

    message = format_signal_message(signal)
    sent = send_telegram_message(message)
    if sent:
        _mark_sent(key)
        logger.info(f"Terkirim: {key}")
    return sent


def notify_startup(futures_count, spot_count):
    text = (
        "🚀 <b>Binance Multi-Market Scanner aktif</b>\n"
        f"Memantau {futures_count} pair futures & {spot_count} pair spot (USDT).\n"
        f"Interval scan: {config.SCAN_INTERVAL_SECONDS // 60} menit."
    )
    send_telegram_message(text)


def notify_error(error_message):
    text = f"⚠️ <b>Scanner error</b>\n<code>{error_message}</code>"
    send_telegram_message(text)
