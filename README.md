# Binance Multi-Market Scanner

Scanner sinyal untuk **Binance Futures + Spot** yang fokus pada data non-mainstream
(funding rate, open interest, long/short ratio, basis futures-spot) — bukan chart
pattern/teknikal biasa. Notifikasi via Telegram bot.

## Sinyal yang dideteksi

**Futures:**
1. **Funding Rate Divergence** — funding ekstrem relatif riwayat simbol sendiri, berlawanan arah dengan harga → indikasi crowded trade rawan squeeze.
2. **OI + Price Divergence** — perubahan open interest signifikan tanpa/berlawanan dengan pergerakan harga → akumulasi/distribusi tersembunyi, atau capitulation.
3. **Long/Short Ratio Extreme** — rasio akun long/short ekstrem + estimasi kasar tekanan leverage dari funding rate.

**Spot:**
4. **Volume Spike Relative** — volume candle adalah outlier (z-score) terhadap baseline rolling milik simbol itu sendiri, bukan threshold absolut.

**Cross-market (butuh simbol yang ada di Futures & Spot):**
5. **Spot-Futures Basis Anomaly** — selisih harga futures vs spot melebar jauh dari kebiasaan simbol itu sendiri.

## Instalasi

```bash
pip install -r requirements.txt
```

Hanya butuh library `requests` — sengaja tanpa numpy/pandas supaya ringan dijalankan di VPS kecil.

## Konfigurasi

Set environment variable untuk bot Telegram kamu:

```bash
export TELEGRAM_BOT_TOKEN="123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export TELEGRAM_CHAT_ID="123456789"
```

Atau edit langsung nilainya di `config.py`.

Semua threshold sinyal (persentil, z-score, dll) ada di `config.py` — silakan
di-tuning sesuai preferensi, mengikuti gaya kerja backtest-driven yang biasa dipakai
di proyek vSynapse (ubah satu parameter, amati dampaknya, iterasi).

## Menjalankan

```bash
python3 scanner.py
```

Scanner akan:
1. Kirim pesan startup ke Telegram (jumlah pair yang dipantau)
2. Loop selamanya, scan semua pair USDT di Futures & Spot tiap 1 jam
3. Kirim tiap sinyal yang terpicu ke Telegram, dengan cooldown 6 jam per (simbol, jenis sinyal, arah) supaya tidak spam

Untuk menjalankan terus-menerus di background di server, disarankan pakai `systemd`,
`screen`/`tmux`, atau `nohup python3 scanner.py &`.

## Struktur file

- `config.py` — semua parameter & threshold, ubah di sini untuk tuning
- `binance_client.py` — wrapper endpoint publik Binance REST (tanpa API key)
- `stats_utils.py` — fungsi statistik kecil (percentile, z-score) tanpa dependency numpy
- `signals.py` — logic 5 sinyal
- `notifier.py` — format pesan & pengiriman Telegram + cooldown
- `scanner.py` — entry point, loop utama

## Catatan penting

- Semua data yang dipakai adalah **data publik Binance** (funding rate, open interest,
  long/short ratio, klines) — tidak ada data privat/insider. Edge dari scanner ini
  datang dari kombinasi & normalisasi statistik (persentil/z-score relatif riwayat
  simbol itu sendiri), bukan dari sumber data rahasia.
- Endpoint `globalLongShortAccountRatio` dan `openInterestHist` Binance hanya
  menyediakan riwayat terbatas (biasanya 1-30 hari tergantung period) — sinyal baru
  bisa kurang akurat untuk koin yang baru listing.
- **Alpha (token pre-listing) sengaja di-skip** dari scope proyek ini sesuai permintaan —
  bisa ditambahkan sebagai modul terpisah nanti kalau dibutuhkan.
- Ini bukan proyek vSynapse — proyek baru yang berdiri sendiri, fokus pada
  data non-chart yang tidak dipakai vSynapse.
- Belum diuji terhadap Binance API secara live (sandbox pembuatan tidak punya akses
  ke domain api.binance.com/fapi.binance.com) — logic sudah divalidasi lewat unit
  test dengan data dummy yang meniru struktur response asli Binance, tapi sebaiknya
  jalankan dulu 1-2 siklus manual dan cek log/Telegram sebelum dibiarkan looping lama.
