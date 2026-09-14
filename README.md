# Binance Multi-Market Scanner

Scanner sinyal untuk **Binance Futures + Spot** yang fokus pada data non-mainstream
(funding rate, open interest, long/short ratio, basis futures-spot) — bukan chart
pattern/teknikal biasa. Notifikasi via Telegram bot. Dijalankan otomatis lewat
**GitHub Actions** (tidak perlu server/VPS sendiri) — cocok dikelola dari HP.

## Sinyal yang dideteksi

**Futures:**
1. **Funding Rate Divergence** — funding ekstrem relatif riwayat simbol sendiri, berlawanan arah dengan harga → indikasi crowded trade rawan squeeze.
2. **OI + Price Divergence** — perubahan open interest signifikan tanpa/berlawanan dengan pergerakan harga → akumulasi/distribusi tersembunyi, atau capitulation.
3. **Long/Short Ratio Extreme** — rasio akun long/short ekstrem + estimasi kasar tekanan leverage dari funding rate.

**Spot:**
4. **Volume Spike Relative** — volume candle adalah outlier (z-score) terhadap baseline rolling milik simbol itu sendiri, bukan threshold absolut.

**Cross-market (butuh simbol yang ada di Futures & Spot):**
5. **Spot-Futures Basis Anomaly** — selisih harga futures vs spot melebar jauh dari kebiasaan simbol itu sendiri.

## Setup (sekali saja, dari HP browser GitHub juga bisa)

### 1. Buat Telegram bot (kalau belum punya)
Chat ke [@BotFather](https://t.me/BotFather) di Telegram, `/newbot`, ikuti instruksinya,
simpan **bot token** yang diberikan. Untuk **chat ID**, kirim pesan apa saja ke bot kamu,
lalu buka `https://api.telegram.org/bot<TOKEN>/getUpdates` di browser — cari angka `"id"`
di dalam objek `"chat"`.

### 2. Simpan token sebagai GitHub Secrets
Di repo ini: **Settings → Secrets and variables → Actions → New repository secret**.
Tambahkan dua secret:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 3. Aktifkan workflow
Workflow di `.github/workflows/scanner.yml` akan otomatis jalan tiap jam (menit ke-0,
waktu UTC) begitu ter-push ke branch `main`. Untuk repo baru kadang GitHub minta
konfirmasi aktivasi workflow sekali di tab **Actions**.

### 4. Test manual (opsional, tanpa nunggu jadwal)
Tab **Actions** → pilih workflow **Binance Multi-Market Scanner** → tombol
**Run workflow**. Bisa dilakukan langsung dari aplikasi GitHub di HP.

## Cara kerja mode GitHub Actions (penting dipahami)

Scanner ini jalan sebagai **single-run**: tiap kali dipicu (oleh cron atau manual),
script menjalankan satu siklus scan penuh lalu langsung selesai/keluar — bukan proses
yang looping selamanya. Ini konsekuensinya:

- **Tidak ada cooldown antar-run.** Tiap run mulai dari container GitHub Actions yang
  bersih, tidak ada memori dari run sebelumnya. Kalau kondisi pasar masih memicu sinyal
  yang sama seperti satu jam lalu, sinyal itu akan dikirim ulang ke Telegram. Ini
  disepakati sebagai trade-off dari mode ini, bukan bug.
- **Interval scan diatur oleh cron di YAML**, bukan oleh kode Python (`config.py` tidak
  lagi punya `SCAN_INTERVAL_SECONDS`). Untuk ubah interval, edit baris `cron:` di
  `.github/workflows/scanner.yml`.
- **Estimasi durasi tiap run**: karena scan mencakup semua pair USDT futures+spot,
  satu run bisa memakan beberapa menit (tergantung jumlah pair aktif saat ini). Ada
  `timeout-minutes: 20` di workflow sebagai guard supaya job tidak menggantung lama
  kalau Binance rate-limit.
- **Risiko rate-limit lebih tinggi dari VPS pribadi**: GitHub Actions shared runner
  berbagi rentang IP dengan banyak job lain di dunia, jadi kemungkinan kena 429/418
  dari Binance sedikit lebih tinggi. Sudah ada retry otomatis di `binance_client.py`
  untuk menangani ini; kalau retry tetap gagal, kamu akan dapat notifikasi error di
  Telegram (atau bisa dicek di tab Actions → run yang gagal, log lengkap ada di sana).

## Struktur file

- `config.py` — semua parameter & threshold, ubah di sini untuk tuning
- `binance_client.py` — wrapper endpoint publik Binance REST (tanpa API key)
- `stats_utils.py` — fungsi statistik kecil (percentile, z-score) tanpa dependency numpy
- `signals.py` — logic 5 sinyal
- `notifier.py` — format pesan & pengiriman Telegram
- `scanner.py` — entry point, satu siklus scan lalu keluar
- `.github/workflows/scanner.yml` — jadwal cron & konfigurasi job GitHub Actions

## Tuning dari HP

Semua threshold sinyal (persentil, z-score, dll) ada di `config.py`. Bisa diedit
langsung dari aplikasi GitHub di HP (buka file → ikon pensil → edit → commit ke
`main`) — perubahan otomatis dipakai di run berikutnya, tidak perlu setup ulang apa pun.

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
- Ini proyek berdiri sendiri, terpisah dari proyek vSynapse — fokus pada data
  non-chart yang tidak dipakai vSynapse.
- Logic sinyal sudah divalidasi lewat unit test dengan data dummy yang meniru
  struktur response asli Binance, tapi **belum pernah dijalankan live** terhadap
  Binance API sungguhan. Sebaiknya jalankan dulu via **Run workflow** manual 1-2 kali
  dan cek hasil di tab Actions + Telegram, sebelum membiarkan jadwal cron berjalan
  tanpa pengawasan.
