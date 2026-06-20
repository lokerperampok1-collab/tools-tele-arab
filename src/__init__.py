"""
Telegram Add Member Tool - Package Initializer
================================================
Modul konfigurasi global: memuat environment variables,
menyiapkan path proyek, dan menyediakan logger terpusat.
"""

import os
import sys
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ── Load Environment Variables dari file .env ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

if not ENV_PATH.exists():
    print(
        f"[ERROR] File .env tidak ditemukan di: {ENV_PATH}\n"
        f"        Salin .env.example menjadi .env lalu isi kredensial Anda."
    )
    sys.exit(1)

load_dotenv(ENV_PATH)

# ── Environment Variables ──
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# Validasi variabel wajib
_missing = []
if not API_ID:
    _missing.append("API_ID")
if not API_HASH:
    _missing.append("API_HASH")
if not BOT_TOKEN:
    _missing.append("BOT_TOKEN")
if not ADMIN_ID:
    _missing.append("ADMIN_ID")

if _missing:
    print(f"[ERROR] Variabel berikut kosong di .env: {', '.join(_missing)}")
    sys.exit(1)

API_ID = int(API_ID)
ADMIN_ID = int(ADMIN_ID)

# ── Path Penting ──
SESSIONS_DIR = PROJECT_ROOT / "sessions"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

SESSIONS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

MEMBERS_CSV = DATA_DIR / "members.csv"

# ── Konfigurasi Logging ke File ──
LOG_FILE = LOGS_DIR / f"activity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("telegram_adder")


def get_session_path(phone: str) -> str:
    """Mengembalikan path session berdasarkan nomor telepon."""
    clean_phone = "".join(c for c in phone if c.isalnum())
    return str(SESSIONS_DIR / clean_phone)
