"""
Kirim notifikasi sinyal ke Telegram.

CATATAN MODE SINGLE-RUN: tidak ada cooldown antar-run di sini. Tiap run
GitHub Actions mulai dari container bersih (tidak ada memori dari run
sebelumnya), jadi sinyal yang sama bisa saja terkirim lagi di run berikutnya
kalau kondisi pasarnya masih memicu sinyal itu -- ini disengaja/disepakati,
bukan bug.
"""

import logging
import requests

import config

logger = logging.getLogger("binance_scanner.notifier")

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
    """Kirim satu sinyal ke Telegram. Mengembalikan True jika berhasil terkirim."""
    message = format_signal_message(signal)
    sent = send_telegram_message(message)
    if sent:
        logger.info(f"Terkirim: {signal['symbol']} / {signal['signal_type']} / {signal['direction']}")
    return sent


def notify_error(error_message):
    text = f"⚠️ <b>Scanner error</b>\n<code>{error_message}</code>"
    send_telegram_message(text)