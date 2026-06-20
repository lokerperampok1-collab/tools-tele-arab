# 🤖 Telegram Add Member Bot

Tool otomatisasi untuk menambahkan member ke grup Telegram — dikendalikan sepenuhnya melalui **Bot Telegram** (bukan CLI).

## 📁 Struktur Proyek

```
arabsaudi_telegram/
├── main.py                 # Entry point (launcher)
├── bot.py                  # Bot Telegram (interface utama)
├── requirements.txt        # Dependencies
├── .env.example            # Template konfigurasi
├── .env                    # Konfigurasi (buat sendiri)
├── .gitignore
├── src/
│   ├── __init__.py         # Config loader & logging
│   └── userbot.py          # Backend operasi (login, scrape, add)
├── sessions/               # File session Telegram
├── data/                   # Output CSV hasil scraping
└── logs/                   # File log aktivitas
```

## 🚀 Cara Install & Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Dapatkan API Credentials

1. Buka [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. Login → buat aplikasi → catat **API_ID** dan **API_HASH**

### 3. Buat Bot di BotFather

1. Buka [@BotFather](https://t.me/BotFather) di Telegram
2. Kirim `/newbot` → ikuti instruksi → catat **BOT_TOKEN**

### 4. Dapatkan Admin ID

1. Buka [@userinfobot](https://t.me/userinfobot) atau [@RawDataBot](https://t.me/RawDataBot)
2. Kirim pesan apa saja → catat **User ID** Anda

### 5. Konfigurasi `.env`

```bash
cp .env.example .env
```

Isi semua variabel:
```env
API_ID=123456
API_HASH=abc123def456...
PHONE_NUMBER=+628xxxxxxxxxx
TWO_FA_PASSWORD=
BOT_TOKEN=123456:ABC-DEF...
ADMIN_ID=123456789
```

## 🎮 Cara Pakai

### Jalankan Bot

```bash
python main.py
```

### Gunakan via Telegram

Buka bot Anda di Telegram, lalu kirim `/start`. Anda akan melihat menu interaktif:

| Tombol | Fungsi |
|--------|--------|
| 🔐 **Login Akun** | Login ke akun Telegram (OTP + 2FA otomatis) |
| 📋 **Scrape Member** | Ambil daftar member dari grup sumber |
| ➕ **Add Member** | Tambahkan member ke grup target |
| 📊 **Status** | Cek status login & data member |
| ❌ **Batal** | Batalkan operasi yang sedang berjalan |

### Alur Kerja

```
/start → Login → Scrape → Add Member
```

1. **Login**: Bot mengirim OTP → ketik kode di chat → login selesai
2. **Scrape**: Kirim link grup sumber → bot mengambil daftar member → simpan CSV
3. **Add**: Kirim link grup target → konfirmasi → bot mulai invite + kirim progress

## 🛡️ Fitur Keamanan

| Fitur | Detail |
|-------|--------|
| Admin-only | Hanya `ADMIN_ID` yang bisa menggunakan bot |
| Delay acak | 15 - 45 detik antar invite |
| Batas per sesi | Maks 50 member per eksekusi |
| FloodWait handling | Auto-pause sesuai durasi penalty Telegram |
| PeerFlood handling | Auto-stop total |
| Error handling | 10+ jenis error Telegram ditangani |

## ⚠️ Peringatan

- **Jangan jalankan terlalu sering**. Telegram sangat ketat terhadap spam.
- **Gunakan akun yang sudah berumur** (bukan akun baru).
- **Maks 50 orang per hari** dari satu akun.
- Tool ini untuk **keperluan edukasi dan legitimate use only**.
