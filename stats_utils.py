"""
Fungsi statistik kecil yang dipakai berulang oleh signals.py.
Sengaja tanpa numpy/pandas supaya dependency scanner ini minimal
(cuma butuh `requests`) -- lebih gampang dijalankan di server kecil / VPS murah.
"""

import math


def percentile_rank(current_value, historical_values):
    """
    Mengembalikan posisi persentil current_value di antara historical_values.
    0.0 = terendah dalam riwayat, 1.0 = tertinggi dalam riwayat.

    historical_values TIDAK perlu mengandung current_value; current_value
    dibandingkan terhadap seluruh riwayat.
    """
    if not historical_values:
        return None
    count_below = sum(1 for v in historical_values if v < current_value)
    return count_below / len(historical_values)


def mean(values):
    if not values:
        return None
    return sum(values) / len(values)


def stdev(values):
    if len(values) < 2:
        return None
    m = mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def zscore(current_value, historical_values):
    """Z-score current_value relatif terhadap historical_values (population dari riwayat)."""
    if not historical_values:
        return None
    m = mean(historical_values)
    s = stdev(historical_values)
    if s is None or s == 0:
        return None
    return (current_value - m) / s


def pct_change(old_value, new_value):
    if old_value in (None, 0):
        return None
    return (new_value - old_value) / abs(old_value) * 100.0
