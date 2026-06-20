# Product Requirements Document (PRD): Telegram Add Member Tool

## 1. Overview
Proyek ini bertujuan untuk membangun sebuah *tool* otomatisasi (bot/script) yang dapat menambahkan anggota (member) ke dalam sebuah grup Telegram target. Tool ini akan memiliki fitur untuk login ke akun Telegram menggunakan API, serta melakukan penambahan member dengan memperhatikan batasan (rate-limit) dari Telegram untuk meminimalisir risiko banned.

## 2. Tujuan (Goals)
- Memudahkan proses penambahan member ke grup Telegram secara massal.
- Mengelola sesi login untuk satu atau lebih akun Telegram (Userbot).
- Mengurangi risiko blokir (banned/limit) akun dengan menerapkan sistem *delay* (jeda) dan penanganan *error*.

## 3. Fitur Utama (Core Features)
1. **Login Akun (Authentication)**
   - Login menggunakan Nomor Telepon, `API_ID`, dan `API_HASH`.
   - Mendukung autentikasi dua langkah (2FA Password) jika diaktifkan.
   - Menyimpan sesi (session) secara lokal agar tidak perlu login berulang kali.
2. **Scraping Member (Opsional tapi Direkomendasikan sebagai sumber data)**
   - Mengambil daftar *username* atau *user ID* dari grup Telegram sumber (Source Group).
   - Menyimpan data hasil *scraping* ke dalam file CSV atau JSON.
3. **Add Member (Penambahan Anggota)**
   - Membaca daftar target (username/ID) dari file sumber data.
   - Mengundang (invite) pengguna tersebut ke grup target (Target Group).
4. **Anti-Ban & Rate Limiting (Krusial)**
   - Jeda waktu (delay) acak antar penambahan (misal: 10 - 30 detik).
   - Penanganan *error* spesifik dari Telegram (contoh: `PeerFloodError`, `UserPrivacyRestrictedError`, `FloodWaitError`).
   - Penghentian otomatis (*auto-stop*) ketika akun terkena pembatasan sementara (*flood wait*).
5. **Logging & Pelaporan**
   - Menampilkan status keberhasilan atau kegagalan penambahan setiap pengguna di terminal/konsol.
   - Menyimpan log aktivitas ke dalam file teks.

## 4. Tech Stack yang Direkomendasikan
- **Bahasa Pemrograman**: Python 3.9+
- **Library Telegram**: `Telethon` atau `Pyrogram` (Sangat direkomendasikan karena stabil, dokumentasi lengkap, dan dirancang khusus untuk interaksi client/userbot).
- **Format Data**: CSV / JSON (untuk menyimpan daftar member), `.env` (untuk kredensial).

---

# Implementation Plan (Rencana Implementasi)

Dokumen ini adalah panduan langkah demi langkah (step-by-step) bagi AI Agent untuk mengimplementasikan *tool* ini dari awal hingga berjalan.

## Fase 1: Setup Proyek & Autentikasi (Login Akun)
1. **Inisialisasi Proyek**:
   - Buat file `requirements.txt` yang berisi library yang dibutuhkan (misal: `telethon`, `python-dotenv`).
   - Buat struktur folder proyek (contoh: `src/`, `data/`, `sessions/`).
2. **Konfigurasi Environment**:
   - Buat file `.env_example` untuk mencontohkan struktur variabel environment (`API_ID`, `API_HASH`, `PHONE_NUMBER`).
3. **Script Login (`src/login.py`)**:
   - Buat script untuk melakukan autentikasi ke Telegram API.
   - Script harus meminta input kode OTP secara interaktif (serta 2FA password jika akun memilikinya).
   - Simpan session hasil login (misal: file `.session`) ke dalam direktori `sessions/`.

## Fase 2: Fitur Scraping Member (Persiapan Data Target)
1. **Script Scraper (`src/scraper.py`)**:
   - Hubungkan ke API menggunakan sesi yang sudah berhasil dibuat di Fase 1.
   - Minta input dari user berupa *username* atau link *Source Group*.
   - Ekstrak data member grup tersebut (User ID, Username, Access Hash, Name).
   - Filter pengguna (jangan masukkan Bot atau Admin).
   - Simpan hasil *scraping* ke `data/members.csv`.

## Fase 3: Fitur Utama (Add Member)
1. **Script Adder (`src/adder.py`)**:
   - Baca data target (baris demi baris) dari `data/members.csv`.
   - Minta input dari user berupa *Target Group* (bisa berupa ID atau username).
   - Buat iterasi (loop) untuk menambahkan (*invite*) user ke grup target.
2. **Implementasi Rate Limiting & Error Handling (Wajib)**:
   - Gunakan `random.sleep()` antar setiap aksi *invite* (contoh rentang aman: 15-45 detik).
   - Tangani error API Telegram secara spesifik:
     - `UserPrivacyRestrictedError`: Pengguna mengunci privasi grup mereka. (Log status, lalu lanjut ke user berikutnya)
     - `UserAlreadyParticipantError`: Pengguna sudah ada di dalam grup target. (Log status, lalu lanjut)
     - `PeerFloodError` / `FloodWaitError`: Akun terkena limit dari Telegram. (Wajib: Berhenti/Pause sementara selama durasi pinalti, jangan dipaksa jalan).

## Fase 4: Pengujian & Penyempurnaan (Testing & Polish)
1. **Dry Run / Validasi**: Implementasikan fitur validasi sederhana untuk mengecek apakah parsing data CSV berjalan dengan baik sebelum memanggil API invite.
2. **Logging Console**: Buat tampilan log di terminal yang rapi dengan indikator warna (misal: Hijau untuk sukses, Merah untuk gagal/error, Kuning untuk delay/sleep).

## Instruksi Tambahan (Guidelines) untuk AI Agent Selanjutnya:
- **Modular Code**: Selalu pisahkan *logic* untuk login, scraping, dan adding ke dalam file/modul yang berbeda agar *codebase* tetap bersih dan mudah dikembangkan.
- **Keamanan**: Jangan pernah menaruh nilai `API_ID` dan `API_HASH` langsung (hardcode) ke dalam *source code*. Wajib baca dari environment variable.
- **Dokumentasi**: Berikan *comments* atau *docstrings* pada fungsi utama dan blok try-catch agar pengembang manusia mudah melakukan *maintenance*.
