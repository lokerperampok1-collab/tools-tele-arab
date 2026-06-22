"""
bot.py — Telegram Bot Interface
==================================
Bot Telegram yang menjadi antarmuka utama untuk seluruh
operasi tool: Login, Scrape Member, dan Add Member.
Semua interaksi dilakukan melalui chat Telegram.

Cara pakai:
    python bot.py
"""

import asyncio
import os

from telethon import TelegramClient, events, Button

from src import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    ADMIN_ID,
    MEMBERS_CSV,
    DATA_DIR,
    SESSIONS_DIR,
    logger,
)
from src import userbot


# ── State Machine ──
# Menyimpan state percakapan per user
user_state = {}


def list_csv_files() -> list[str]:
    """Mengembalikan daftar file .csv di dalam directory data."""
    import glob
    files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    return sorted([os.path.basename(f) for f in files])


def sanitize_csv_filename(csv_name: str) -> str:
    """Membersihkan nama file CSV dari input user agar aman dan konsisten."""
    import re
    if not csv_name or csv_name.strip().lower() in ("default", "members"):
        return "members.csv"
    
    name = os.path.basename(csv_name)
    name = re.sub(r'[^\w\s\.-]', '', name)
    name = name.strip()
    
    if not name.lower().endswith(".csv"):
        name = f"{name}.csv"
        
    if name.lower() == ".csv" or not name:
        return "members.csv"
        
    return name


# State constants
STATE_IDLE = "idle"
STATE_AWAITING_PHONE = "awaiting_phone"
STATE_AWAITING_OTP = "awaiting_otp"
STATE_AWAITING_2FA = "awaiting_2fa"
STATE_AWAITING_SOURCE_GROUP = "awaiting_source_group"
STATE_AWAITING_TARGET_GROUP = "awaiting_target_group"
STATE_AWAITING_CONFIRM = "awaiting_confirm"
STATE_AWAITING_PREFIX_NAME = "awaiting_prefix_name"
STATE_AWAITING_BASE_NUMBER = "awaiting_base_number"
STATE_AWAITING_GEN_COUNT = "awaiting_gen_count"
STATE_AWAITING_SCR_CSV_FILENAME = "awaiting_scr_csv_filename"
STATE_AWAITING_CNT_CSV_FILENAME = "awaiting_cnt_csv_filename"
STATE_AWAITING_VAL_CSV_FILENAME = "awaiting_val_csv_filename"
STATE_AWAITING_GROUP_TITLE = "awaiting_group_title"
STATE_AWAITING_GROUP_ABOUT = "awaiting_group_about"
STATE_BUSY = "busy"  # Sedang memproses (scrape/add)


def is_admin(user_id: int) -> bool:
    """Cek apakah user adalah admin."""
    return user_id == ADMIN_ID


def get_state(user_id: int) -> str:
    """Ambil state user saat ini."""
    return user_state.get(user_id, {}).get("state", STATE_IDLE)


def set_state(user_id: int, state: str, **data):
    """Set state user dengan data tambahan."""
    if user_id not in user_state:
        user_state[user_id] = {}
    user_state[user_id]["state"] = state
    user_state[user_id].update(data)


def get_data(user_id: int, key: str, default=None):
    """Ambil data dari state user."""
    return user_state.get(user_id, {}).get(key, default)


def clear_state(user_id: int):
    """Reset state user ke idle."""
    user_state[user_id] = {"state": STATE_IDLE}


# ── Bot Client ──
bot = TelegramClient("bot_session", API_ID, API_HASH)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MENU UTAMA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WELCOME_TEXT = """
🤖 **Telegram Add Member Tool**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Selamat datang! Bot ini membantu Anda menambahkan member ke grup Telegram secara otomatis.

**Pilih menu di bawah:**
"""

MAIN_BUTTONS = [
    [Button.inline("🔐 Login Akun", b"menu_login")],
    [Button.inline("📋 Scrape Member", b"menu_scrape")],
    [Button.inline("➕ Add Member", b"menu_add")],
    [Button.inline("🏗️ Buat Grup Otomatis", b"menu_create_group")],
    [Button.inline("🔢 Generator & Validator", b"menu_gen_val")],
    [Button.inline("📄 Lihat Data CSV", b"menu_view_csv")],
    [Button.inline("📊 Status", b"menu_status")],
    [Button.inline("❌ Batal / Reset", b"menu_cancel")],
]


@bot.on(events.NewMessage(pattern="/start"))
async def cmd_start(event):
    """Handler /start — tampilkan menu utama."""
    if not is_admin(event.sender_id):
        await event.respond("⛔ Anda tidak memiliki akses ke bot ini.")
        return

    clear_state(event.sender_id)
    await event.respond(WELCOME_TEXT, buttons=MAIN_BUTTONS, parse_mode="md")


@bot.on(events.NewMessage(pattern="/menu"))
async def cmd_menu(event):
    """Handler /menu — kembali ke menu utama."""
    if not is_admin(event.sender_id):
        return
    clear_state(event.sender_id)
    await event.respond(WELCOME_TEXT, buttons=MAIN_BUTTONS, parse_mode="md")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: MENU LOGIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Pemetaan phone -> asyncio.Task untuk melacak task aktif per akun
active_tasks = {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BACKGROUND TASK WRAPPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def run_add_task(phone: str, target: str, members: list[dict], admin_id: int):
    """Wrapper untuk menjalankan proses add member di background."""
    async def on_progress(msg):
        try:
            full_msg = f"📱 **Akun**: `{phone}`\n{msg}"
            await bot.send_message(admin_id, full_msg, parse_mode="md")
        except Exception:
            pass

    try:
        result = await userbot.add_members(phone, target, members, progress_callback=on_progress)
        
        if not result["success"]:
            await bot.send_message(
                admin_id,
                f"❌ **Gagal!** (Akun: `{phone}`)\n{result['error']}",
                parse_mode="md",
            )
            return

        # Laporan akhir
        report = (
            f"📊 **LAPORAN AKHIR**\n"
            f"📱 Akun: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Grup: **{result['group_title']}**\n\n"
            f"✅ Berhasil ditambahkan: **{result['added']}**\n"
            f"⏩ Dilewati (skip): **{result['skipped']}**\n"
            f"❌ Gagal (error): **{result['failed']}**\n"
            f"📦 Total diproses: **{result['total_processed']}/{result['total_members']}**\n"
            f"⏱️ Waktu: **{result['elapsed_minutes']} menit**\n"
        )

        if result.get("stopped_reason"):
            report += f"\n⚠️ Alasan berhenti: {result['stopped_reason']}\n"

        await bot.send_message(
            admin_id,
            report,
            parse_mode="md",
        )
    except Exception as e:
        logger.error(f"Error running add task for {phone}: {e}")
        try:
            await bot.send_message(admin_id, f"❌ **Error tak terduga** pada akun `{phone}`: {e}")
        except Exception:
            pass
    finally:
        if phone in active_tasks:
            del active_tasks[phone]


async def run_scrape_task(phone: str, source: str, admin_id: int, csv_filename: str = "members.csv"):
    """Wrapper untuk menjalankan proses scrape grup di background."""
    async def on_progress(progress_msg):
        try:
            await bot.send_message(admin_id, f"📱 **Akun**: `{phone}`\n{progress_msg}", parse_mode="md")
        except Exception:
            pass

    try:
        result = await userbot.scrape_members(phone, source, progress_callback=on_progress, csv_filename=csv_filename)
        if not result["success"]:
            await bot.send_message(
                admin_id,
                f"❌ **Scrape Gagal!** (Akun: `{phone}`)\n\n{result['error']}",
                parse_mode="md",
            )
            return

        await bot.send_message(
            admin_id,
            f"✅ **Scrape Berhasil!**\n"
            f"📱 Akun: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 Grup: **{result['group_title']}**\n"
            f"👥 Total ditemukan: **{result['total']}**\n"
            f"💾 Tersimpan: **{result['saved']}** member\n"
            f"🤖 Bot dilewati: **{result['skipped_bots']}**\n"
            f"💀 Akun terhapus: **{result['skipped_deleted']}**\n\n"
            f"Data disimpan ke `{csv_filename}` (Siap digunakan untuk Add Member)",
            parse_mode="md",
        )
    except Exception as e:
        logger.error(f"Error running scrape task for {phone}: {e}")
        try:
            await bot.send_message(admin_id, f"❌ **Error tak terduga** pada akun `{phone}` saat scrape: {e}")
        except Exception:
            pass
    finally:
        if phone in active_tasks:
            del active_tasks[phone]


async def run_scrape_contacts_task(phone: str, admin_id: int, csv_filename: str = "members.csv"):
    """Wrapper untuk menjalankan proses scrape kontak di background."""
    async def on_progress(progress_msg):
        try:
            await bot.send_message(admin_id, f"📱 **Akun**: `{phone}`\n{progress_msg}", parse_mode="md")
        except Exception:
            pass

    try:
        result = await userbot.scrape_contacts(phone, progress_callback=on_progress, csv_filename=csv_filename)
        if not result["success"]:
            await bot.send_message(
                admin_id,
                f"❌ **Scrape Kontak Gagal!** (Akun: `{phone}`)\n\n{result['error']}",
                parse_mode="md",
            )
            return

        await bot.send_message(
            admin_id,
            f"✅ **Scrape Kontak Berhasil!**\n"
            f"📱 Akun: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📇 Total kontak ditemukan: **{result['total']}**\n"
            f"💾 Tersimpan: **{result['saved']}** kontak\n"
            f"🤖 Bot dilewati: **{result['skipped_bots']}**\n"
            f"💀 Akun terhapus: **{result['skipped_deleted']}**\n\n"
            f"Data disimpan ke `{csv_filename}` (Siap digunakan untuk Add Member)",
            parse_mode="md",
        )
    except Exception as e:
        logger.error(f"Error running scrape contacts task for {phone}: {e}")
        try:
            await bot.send_message(admin_id, f"❌ **Error tak terduga** pada akun `{phone}` saat scrape kontak: {e}")
        except Exception:
            pass
    finally:
        if phone in active_tasks:
            del active_tasks[phone]


async def run_validate_task(phone: str, numbers: list[str], admin_id: int, prefix_name: str, csv_filename: str = "members.csv"):
    """Wrapper untuk menjalankan validasi nomor generator di background."""
    async def on_progress(progress_msg):
        try:
            await bot.send_message(admin_id, f"📱 **Akun**: `{phone}`\n{progress_msg}", parse_mode="md")
        except Exception:
            pass

    try:
        result = await userbot.validate_phone_numbers(phone, numbers, prefix_name=prefix_name, progress_callback=on_progress, csv_filename=csv_filename)
        if not result["success"]:
            await bot.send_message(
                admin_id,
                f"❌ **Validasi Gagal!** (Akun: `{phone}`)\n\n{result['error']}",
                parse_mode="md",
            )
            return

        report = (
            f"✅ **Proses Validasi Selesai!**\n"
            f"📱 Akun: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Total nomor di-scan: **{result['total_checked']}**\n"
            f"👤 Terdaftar Telegram: **{result['valid_count']}** akun\n\n"
        )
        if result['valid_count'] > 0:
            report += f"💾 Akun terdaftar telah disimpan ke `{csv_filename}` dan siap langsung di-invite via menu **Add Member**!"
        else:
            report += "⚠️ Tidak ada nomor yang terdaftar di Telegram dari hasil scan ini."

        await bot.send_message(admin_id, report, parse_mode="md")
    except Exception as e:
        logger.error(f"Error running validate task for {phone}: {e}")
        try:
            await bot.send_message(admin_id, f"❌ **Error tak terduga** pada akun `{phone}` saat validasi: {e}")
        except Exception:
            pass
    finally:
        if phone in active_tasks:
            del active_tasks[phone]


async def run_create_group_task(phone: str, title: str, about: str, admin_id: int):
    """Wrapper untuk menjalankan proses pembuatan grup di background."""
    try:
        result = await userbot.create_megagroup(phone, title, about)
        if not result["success"]:
            await bot.send_message(
                admin_id,
                f"❌ **Gagal Membuat Grup!** (Akun: `{phone}`)\n\n{result['error']}",
                parse_mode="md",
            )
            return

        report = (
            f"🏗️ **GRUP BERHASIL DIBUAT!**\n"
            f"📱 Akun: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏷️ Nama Grup: **{result['group_title']}**\n"
            f"🆔 ID Grup: `{result['group_id']}`\n"
        )
        if result.get("invite_link"):
            report += f"🔗 Tautan Undangan: {result['invite_link']}\n"
        else:
            report += f"⚠️ Tidak dapat menghasilkan tautan undangan otomatis.\n"

        await bot.send_message(
            admin_id,
            report,
            parse_mode="md",
        )
    except Exception as e:
        logger.error(f"Error running create group task for {phone}: {e}")
        try:
            await bot.send_message(admin_id, f"❌ **Error tak terduga** pada akun `{phone}` saat membuat grup: {e}")
        except Exception:
            pass
    finally:
        if phone in active_tasks:
            del active_tasks[phone]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: MENU LOGIN & MANAJEMEN AKUN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_login"))
async def cb_login(event):
    """Menampilkan manajemen akun (daftar login, tambah, hapus)."""
    if not is_admin(event.sender_id):
        return

    await event.answer()
    
    sessions = userbot.list_sessions()
    
    if sessions:
        tasks = []
        for p in sessions:
            if p in active_tasks:
                async def _fake(phone=p):
                    return {"authorized": True, "user": None, "phone": phone, "error": "Task sedang berjalan"}
                tasks.append(_fake())
            else:
                tasks.append(userbot.check_session(p))
        results = await asyncio.gather(*tasks)
    else:
        results = []

    text = "🔐 **Manajemen Akun (Userbot)**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if not results:
        text += "Belum ada akun yang terdaftar."
    else:
        text += "**Daftar Akun Terhubung:**\n"
        for idx, res in enumerate(results, start=1):
            phone = res["phone"]
            if res["authorized"]:
                me = res["user"]
                name = f"{me.first_name or ''} {me.last_name or ''}".strip()
                text += f"{idx}. `{phone}` - **{name}** (✅ Aktif)\n"
            else:
                text += f"{idx}. `{phone}` - (❌ Expired/Error: {res['error'] or 'Login Ulang'})\n"
    
    buttons = [
        [Button.inline("➕ Tambah Akun Baru", b"login_add_new")],
    ]
    
    if sessions:
        buttons.append([Button.inline("🗑️ Hapus Akun", b"login_delete_list")])
        
    buttons.append([Button.inline("🔙 Menu Utama", b"back_menu")])

    await event.respond(text, buttons=buttons, parse_mode="md")


@bot.on(events.CallbackQuery(data=b"login_add_new"))
async def cb_login_add_new(event):
    """Meminta nomor telepon untuk login baru."""
    if not is_admin(event.sender_id):
        return

    await event.answer()
    
    set_state(event.sender_id, STATE_AWAITING_PHONE)
    await event.respond(
        "🔐 **Login Akun Baru**\n\n"
        "Kirim **nomor telepon** akun baru yang ingin ditambahkan:\n\n"
        "_Contoh: `+628123456789`_",
        buttons=[[Button.inline("❌ Batal", b"menu_login")]],
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=b"login_delete_list"))
async def cb_login_delete_list(event):
    """Menampilkan pilihan akun untuk dihapus."""
    if not is_admin(event.sender_id):
        return

    await event.answer()
    
    sessions = userbot.list_sessions()
    if not sessions:
        await event.respond("Tidak ada akun untuk dihapus.", buttons=[[Button.inline("🔙 Kembali", b"menu_login")]])
        return

    buttons = []
    for phone in sessions:
        buttons.append([Button.inline(f"🗑️ Hapus {phone}", f"del_acc_{phone}".encode('utf-8'))])
        
    buttons.append([Button.inline("🔙 Kembali", b"menu_login")])
    
    await event.respond(
        "🗑️ **Pilih Akun yang Ingin Dihapus**\n\n"
        "Menghapus akun akan menghapus file session lokal. Akun di Telegram sendiri tidak akan terpengaruh.",
        buttons=buttons,
        parse_mode="md"
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"del_acc_")))
async def cb_delete_account(event):
    """Menghapus session file untuk nomor telepon tertentu."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("del_acc_", "")
    await event.answer(f"Menghapus {phone}...")
    
    session_file = userbot.SESSIONS_DIR / f"{phone.replace('+', '')}.session"
    if session_file.exists():
        try:
            session_file.unlink()
            await event.respond(
                f"✅ Session untuk akun `{phone}` telah dihapus.",
                buttons=[[Button.inline("🔙 Kembali", b"menu_login")]],
                parse_mode="md"
            )
        except Exception as e:
            await event.respond(
                f"❌ Gagal menghapus file session: {e}",
                buttons=[[Button.inline("🔙 Kembali", b"menu_login")]],
                parse_mode="md"
            )
    else:
        await event.respond(
            f"❌ File session untuk `{phone}` tidak ditemukan.",
            buttons=[[Button.inline("🔙 Kembali", b"menu_login")]],
            parse_mode="md"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: MENU SCRAPE (PILIH AKUN & METODE)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_scrape"))
async def cb_scrape(event):
    """Menampilkan pilihan akun untuk melakukan scrape."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    sessions = userbot.list_sessions()
    if not sessions:
        await event.respond(
            "⚠️ **Belum ada akun!**\nSilakan login akun terlebih dahulu.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    tasks = []
    for p in sessions:
        if p in active_tasks:
            async def _fake(phone=p):
                return {"authorized": True, "user": None, "phone": phone, "error": "Task sedang berjalan"}
            tasks.append(_fake())
        else:
            tasks.append(userbot.check_session(p))
    results = await asyncio.gather(*tasks)
    active_sessions = [res["phone"] for res in results if res["authorized"]]

    if not active_sessions:
        await event.respond(
            "⚠️ **Tidak ada akun aktif!**\nSemua session terputus. Silakan login kembali.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    buttons = []
    for phone in active_sessions:
        buttons.append([Button.inline(f"📱 Akun: {phone}", f"scr_sel_{phone}".encode('utf-8'))])
        
    buttons.append([Button.inline("🔙 Menu Utama", b"back_menu")])

    await event.respond(
        "📋 **Scrape Member — Pilih Akun**\n\n"
        "Pilih akun yang ingin Anda gunakan untuk melakukan scrape:",
        buttons=buttons,
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"scr_sel_")))
async def cb_scrape_account_selected(event):
    """Menampilkan pilihan sumber scrape setelah memilih akun."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("scr_sel_", "")
    await event.answer()

    if phone in active_tasks:
        await event.respond(
            f"⚠️ Akun `{phone}` sedang sibuk menjalankan task lain.\n"
            "Silakan tunggu hingga selesai atau pilih akun lain.",
            buttons=[[Button.inline("🔙 Kembali ke Pilihan Akun", b"menu_scrape")]],
            parse_mode="md"
        )
        return

    await event.respond(
        f"📋 **Scrape Member (Akun: `{phone}`)**\n\n"
        "Silakan pilih dari mana Anda ingin mengambil daftar member:\n\n"
        "1. **👥 Scrape dari Grup**: Mengambil member dari grup/channel Telegram lain.\n"
        "2. **📇 Scrape dari Kontak**: Mengambil daftar kontak dari akun ini.",
        buttons=[
            [Button.inline("👥 Scrape dari Grup", f"scr_grp_{phone}".encode('utf-8'))],
            [Button.inline("📇 Scrape dari Kontak", f"scr_cnt_{phone}".encode('utf-8'))],
            [Button.inline("🔙 Kembali", b"menu_scrape")],
        ],
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"scr_grp_")))
async def cb_scrape_group_selected(event):
    """Meminta nama grup untuk proses scrape."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("scr_grp_", "")
    await event.answer()

    set_state(event.sender_id, STATE_AWAITING_SOURCE_GROUP, phone=phone)
    await event.respond(
        f"📋 **Scrape dari Grup (Akun: `{phone}`)**\n\n"
        "Kirim username atau link **grup sumber** yang ingin di-scrape:\n\n"
        "_Contoh:_\n"
        "• `@nama_grup`\n"
        "• `https://t.me/nama_grup`\n"
        "• `-100123456789`",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"scr_cnt_")))
async def cb_scrape_contacts_selected(event):
    """Meminta nama file CSV untuk proses scrape kontak."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("scr_cnt_", "")
    await event.answer()

    if phone in active_tasks:
        await event.respond(f"⚠️ Akun `{phone}` sedang sibuk menjalankan task lain.")
        return

    set_state(event.sender_id, STATE_AWAITING_CNT_CSV_FILENAME, phone=phone)
    await event.respond(
        f"📋 **Scrape Kontak (Akun: `{phone}`)**\n\n"
        "Masukkan **Nama File CSV** untuk menyimpan hasil scrape (tanpa `.csv`):\n"
        "_(Contoh: `kontak_saya` -> disimpan sebagai `kontak_saya.csv`)_\n\n"
        "Ketik `members` atau langsung kirim teks untuk menggunakan file default (`members.csv`):",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: MENU ADD MEMBER (PILIH AKUN)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_add"))
@bot.on(events.CallbackQuery(data=b"menu_add"))
async def cb_add(event):
    """Menampilkan pilihan metode penambahan member (CSV atau Kontak Langsung)."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    await event.respond(
        "➕ **Pilih Sumber Member untuk di-Invite**\n\n"
        "Silakan tentukan dari mana daftar member akan diambil:\n\n"
        "1. **📂 Dari Hasil Scrape (`members.csv`)**: Menggunakan daftar member dari grup/channel yang sudah di-scrape sebelumnya.\n"
        "2. **📇 Dari Kontak Akun Langsung**: Mengambil kontak aktif akun secara real-time dan langsung mengundangnya (tanpa scrape manual).",
        buttons=[
            [Button.inline("📂 Dari Hasil Scrape (CSV)", b"add_from_csv")],
            [Button.inline("📇 Dari Kontak Akun Langsung", b"add_from_contacts")],
            [Button.inline("🔙 Menu Utama", b"back_menu")],
        ],
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=b"add_from_csv"))
async def cb_add_from_csv(event):
    """Pilihan file CSV untuk add member."""
    if not is_admin(event.sender_id):
        return
    await event.answer()

    files = list_csv_files()
    if not files:
        await event.respond(
            "⚠️ **Data CSV kosong!**\n"
            "Belum ada file CSV hasil scrape atau validasi. Silakan lakukan Scrape Member atau Validasi terlebih dahulu.",
            buttons=[
                [Button.inline("📋 Scrape Member", b"menu_scrape")],
                [Button.inline("🔙 Kembali", b"menu_add")],
            ],
            parse_mode="md",
        )
        return

    buttons = []
    for f in files:
        buttons.append([Button.inline(f"📄 {f}", f"addcsvfile_{f}".encode('utf-8'))])
    buttons.append([Button.inline("🔙 Kembali", b"menu_add")])

    await event.respond(
        "➕ **Add Member (CSV) — Pilih File CSV**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Silakan pilih file CSV yang berisi daftar member yang ingin Anda undang:",
        buttons=buttons,
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"addcsvfile_")))
async def cb_addcsvfile_selected(event):
    if not is_admin(event.sender_id):
        return
    
    filename = os.path.basename(event.data.decode('utf-8').replace("addcsvfile_", ""))
    await event.answer()

    # Load members dari file csv terpilih
    members = userbot.load_members(csv_filename=filename)
    
    # Simpan nama file csv dan list members ke data user state
    set_state(event.sender_id, "add_csv_acc_select", csv_filename=filename, members=members)

    sessions = userbot.list_sessions()
    if not sessions:
        await event.respond(
            "⚠️ **Belum ada akun!**\nSilakan login akun terlebih dahulu.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    tasks = []
    for p in sessions:
        if p in active_tasks:
            async def _fake(phone=p):
                return {"authorized": True, "user": None, "phone": phone, "error": "Task sedang berjalan"}
            tasks.append(_fake())
        else:
            tasks.append(userbot.check_session(p))
    results = await asyncio.gather(*tasks)
    active_sessions = [res["phone"] for res in results if res["authorized"]]

    if not active_sessions:
        await event.respond(
            "⚠️ **Tidak ada akun aktif!**\nSemua session terputus. Silakan login kembali.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    buttons = []
    for phone in active_sessions:
        buttons.append([Button.inline(f"📱 Akun: {phone}", f"add_csv_sel_{phone}".encode('utf-8'))])
        
    buttons.append([Button.inline("🔙 Kembali", b"add_from_csv")])

    await event.respond(
        f"➕ **Add Member (CSV: `{filename}`) — Pilih Akun**\n\n"
        f"📊 Data tersedia: **{len(members)} member**\n\n"
        f"Pilih akun yang ingin digunakan untuk mengundang:",
        buttons=buttons,
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=b"add_from_contacts"))
async def cb_add_from_contacts(event):
    """Pilihan akun untuk add member langsung dari kontak akun."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    sessions = userbot.list_sessions()
    if not sessions:
        await event.respond(
            "⚠️ **Belum ada akun!**\nSilakan login akun terlebih dahulu.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    tasks = []
    for p in sessions:
        if p in active_tasks:
            async def _fake(phone=p):
                return {"authorized": True, "user": None, "phone": phone, "error": "Task sedang berjalan"}
            tasks.append(_fake())
        else:
            tasks.append(userbot.check_session(p))
    results = await asyncio.gather(*tasks)
    active_sessions = [res["phone"] for res in results if res["authorized"]]

    if not active_sessions:
        await event.respond(
            "⚠️ **Tidak ada akun aktif!**\nSemua session terputus. Silakan login kembali.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    buttons = []
    for phone in active_sessions:
        buttons.append([Button.inline(f"📱 Akun: {phone}", f"add_cnt_sel_{phone}".encode('utf-8'))])
        
    buttons.append([Button.inline("🔙 Kembali", b"menu_add")])

    await event.respond(
        f"➕ **Add Member (Kontak) — Pilih Akun**\n\n"
        f"Pilih akun yang ingin digunakan untuk mengambil kontak dan mengundang:",
        buttons=buttons,
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"add_csv_sel_")))
async def cb_add_csv_account_selected(event):
    """Meminta grup target untuk proses invite menggunakan data CSV."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("add_csv_sel_", "")
    await event.answer()

    if phone in active_tasks:
        await event.respond(
            f"⚠️ Akun `{phone}` sedang sibuk menjalankan task lain.\n"
            "Silakan tunggu hingga selesai atau pilih akun lain.",
            buttons=[[Button.inline("🔙 Kembali", b"menu_add")]],
            parse_mode="md"
        )
        return

    csv_filename = get_data(event.sender_id, "csv_filename", "members.csv")
    members = userbot.load_members(csv_filename=csv_filename)
    set_state(event.sender_id, STATE_AWAITING_TARGET_GROUP, phone=phone, members=members, source_type="csv", csv_filename=csv_filename)
    await event.respond(
        f"➕ **Add Member dari CSV (Akun: `{phone}`)**\n\n"
        f"Kirim username atau link **grup target**:\n\n"
        f"_Contoh:_\n"
        f"• `@grup_target`\n"
        f"• `https://t.me/grup_target`",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"add_cnt_sel_")))
async def cb_add_contacts_account_selected(event):
    """Meminta grup target untuk proses invite langsung dari kontak."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("add_cnt_sel_", "")
    await event.answer()

    if phone in active_tasks:
        await event.respond(
            f"⚠️ Akun `{phone}` sedang sibuk menjalankan task lain.\n"
            "Silakan tunggu hingga selesai atau pilih akun lain.",
            buttons=[[Button.inline("🔙 Kembali", b"menu_add")]],
            parse_mode="md"
        )
        return

    set_state(event.sender_id, STATE_AWAITING_TARGET_GROUP, phone=phone, source_type="contacts")
    await event.respond(
        f"➕ **Add Member dari Kontak Akun (Akun: `{phone}`)**\n\n"
        f"Kirim username atau link **grup target**:\n\n"
        f"_Contoh:_\n"
        f"• `@grup_target`\n"
        f"• `https://t.me/grup_target`",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: STATUS & PEMBATALAN TASK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_status"))
async def cb_status(event):
    """Menampilkan status semua akun dan task yang sedang aktif."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    sessions = userbot.list_sessions()
    if not sessions:
        await event.respond(
            "📊 **Status Tool**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ Belum ada akun yang terhubung.",
            buttons=[
                [Button.inline("🔐 Login Akun", b"menu_login")],
                [Button.inline("🔙 Menu Utama", b"back_menu")]
            ],
            parse_mode="md"
        )
        return

    tasks = []
    for p in sessions:
        if p in active_tasks:
            async def _fake(phone=p):
                return {"authorized": True, "user": None, "phone": phone, "error": "Task sedang berjalan"}
            tasks.append(_fake())
        else:
            tasks.append(userbot.check_session(p))
    results = await asyncio.gather(*tasks)

    status_text = "📊 **Status Multi-Akun & Task**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    status_text += "**Daftar Akun:**\n"
    active_count = 0
    for res in results:
        phone = res["phone"]
        if res["authorized"]:
            me = res["user"]
            name = f"{me.first_name or ''} {me.last_name or ''}".strip()
            username = f"(@{me.username})" if me.username else ""
            status_text += f"• `{phone}`: **{name}** {username} - ✅ Aktif\n"
            active_count += 1
        else:
            status_text += f"• `{phone}`: ❌ Terputus / Expired\n"

    status_text += f"\nTotal akun aktif: **{active_count}/{len(sessions)}**\n\n"

    status_text += "**Task Berjalan:**\n"
    if not active_tasks:
        status_text += "_Tidak ada task aktif saat ini._\n"
    else:
        for phone in active_tasks:
            status_text += f"• Akun `{phone}`: ⚡ Sedang memproses...\n"

    members = userbot.load_members()
    status_text += f"\n📊 **Data Member**: **{len(members)} member** di `members.csv`"

    await event.respond(
        status_text,
        buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
        parse_mode="md"
    )


@bot.on(events.CallbackQuery(data=b"menu_view_csv"))
async def cb_view_csv_list(event):
    if not is_admin(event.sender_id):
        return
    await event.answer()
    
    files = list_csv_files()
    if not files:
        await event.respond(
            "📂 **Data CSV**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ Belum ada file CSV hasil scrape atau validasi. Silakan lakukan Scrape Member atau Validasi terlebih dahulu.",
            buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
            parse_mode="md"
        )
        return

    buttons = []
    for f in files:
        buttons.append([Button.inline(f"📄 {f}", f"vcsv_{f}".encode('utf-8'))])
    buttons.append([Button.inline("🔙 Menu Utama", b"back_menu")])

    await event.respond(
        "📂 **Pilih File CSV untuk Dilihat:**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Silakan pilih file CSV di bawah ini untuk melihat pratinjau data atau mengunduhnya:",
        buttons=buttons,
        parse_mode="md"
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"vcsv_")))
async def cb_view_csv_file(event):
    if not is_admin(event.sender_id):
        return
    
    filename = os.path.basename(event.data.decode('utf-8').replace("vcsv_", ""))
    await event.answer()

    csv_path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(csv_path):
        await event.respond(f"⚠️ File `{filename}` tidak ditemukan.")
        return

    import csv
    try:
        rows = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                if row:
                    rows.append(row)
    except Exception as e:
        await event.respond(
            f"❌ Gagal membaca file `{filename}`: {e}",
            buttons=[[Button.inline("🔙 Kembali", b"menu_view_csv")]]
        )
        return

    total_members = len(rows)
    # Tampilkan 20 member pertama
    limit = 20
    text_lines = [
        f"📂 **File: `{filename}`**\n"
        f"📊 **Total**: {total_members} member\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    
    for idx, row in enumerate(rows[:limit], 1):
        user_id = row[0] if len(row) > 0 else "N/A"
        username = row[2] if len(row) > 2 and row[2] else "N/A"
        first_name = row[3] if len(row) > 3 else ""
        last_name = row[4] if len(row) > 4 else ""
        full_name = f"{first_name} {last_name}".strip() or "N/A"
        
        text_lines.append(f"{idx}. `{user_id}` | @{username} | **{full_name}**")

    if total_members > limit:
        text_lines.append(f"\n_... dan {total_members - limit} member lainnya._")

    message_text = "\n".join(text_lines)

    buttons = [
        [
            Button.inline("📥 Unduh CSV", f"dlcsv_{filename}".encode('utf-8')),
            Button.inline("🔙 Kembali", b"menu_view_csv")
        ]
    ]

    await event.respond(message_text, buttons=buttons, parse_mode="md")


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"dlcsv_")))
async def cb_download_csv_file(event):
    if not is_admin(event.sender_id):
        return
    
    filename = os.path.basename(event.data.decode('utf-8').replace("dlcsv_", ""))
    await event.answer("Mengirim file...")

    csv_path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(csv_path):
        await event.respond(f"⚠️ File `{filename}` tidak ditemukan.")
        return

    try:
        await bot.send_file(
            event.sender_id,
            csv_path,
            caption=f"📄 **File: `{filename}`**\nTotal: {sum(1 for _ in open(csv_path, encoding='utf-8')) - 1} member.",
            parse_mode="md"
        )
    except Exception as e:
        await event.respond(f"❌ Gagal mengirim file: {e}")


@bot.on(events.CallbackQuery(data=b"menu_cancel"))
async def cb_cancel(event):
    """Menampilkan pilihan pembatalan (percakapan atau task background)."""
    if not is_admin(event.sender_id):
        return
    await event.answer()
    
    buttons = [
        [Button.inline("🧹 Reset Percakapan", b"cancel_state_reset")],
    ]
    
    if active_tasks:
        buttons.append([Button.inline("🛑 Hentikan Task Aktif", b"cancel_tasks_list")])
        
    buttons.append([Button.inline("🔙 Menu Utama", b"back_menu")])

    await event.respond(
        "❌ **Pilihan Pembatalan / Reset**\n\n"
        "Pilih tindakan pembatalan di bawah ini:",
        buttons=buttons,
        parse_mode="md"
    )


@bot.on(events.CallbackQuery(data=b"cancel_state_reset"))
async def cb_cancel_state_reset(event):
    """Mereset state percakapan admin ke IDLE."""
    if not is_admin(event.sender_id):
        return
    await event.answer("State direset")
    clear_state(event.sender_id)
    await event.respond(
        "🧹 Status input percakapan telah direset ke Idle.\n",
        buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
    )


@bot.on(events.CallbackQuery(data=b"cancel_tasks_list"))
async def cb_cancel_tasks_list(event):
    """Menampilkan daftar task aktif untuk dihentikan."""
    if not is_admin(event.sender_id):
        return

    await event.answer()
    
    if not active_tasks:
        await event.respond("Tidak ada task aktif saat ini.", buttons=[[Button.inline("🔙 Kembali", b"back_menu")]])
        return

    buttons = []
    for phone in active_tasks:
        buttons.append([Button.inline(f"🛑 Hentikan `{phone}`", f"stop_tsk_{phone}".encode('utf-8'))])
        
    buttons.append([Button.inline("🔙 Kembali", b"back_menu")])
    
    await event.respond(
        "🛑 **Pilih Task yang Ingin Dihentikan**\n\n"
        "Pilih akun di bawah untuk menghentikan proses scraping/adding yang sedang berjalan:",
        buttons=buttons,
        parse_mode="md"
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"stop_tsk_")))
async def cb_stop_task(event):
    """Membatalkan asyncio Task untuk nomor tertentu."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("stop_tsk_", "")
    await event.answer(f"Menghentikan task `{phone}`...")
    
    if phone in active_tasks:
        task = active_tasks[phone]
        task.cancel()
        if phone in active_tasks:
            del active_tasks[phone]
        await event.respond(
            f"✅ Task pada akun `{phone}` telah dihentikan secara paksa.",
            buttons=[[Button.inline("🔙 Kembali ke Menu Utama", b"back_menu")]],
            parse_mode="md"
        )
    else:
        await event.respond(
            f"❌ Task pada akun `{phone}` tidak ditemukan atau sudah selesai.",
            buttons=[[Button.inline("🔙 Kembali ke Menu Utama", b"back_menu")]],
            parse_mode="md"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: AUTO CREATE GROUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_create_group"))
async def cb_create_group(event):
    """Pilihan akun untuk membuat grup baru."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    sessions = userbot.list_sessions()
    if not sessions:
        await event.respond(
            "⚠️ **Belum ada akun!**\nSilakan login akun terlebih dahulu.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    tasks = []
    for p in sessions:
        if p in active_tasks:
            async def _fake(phone=p):
                return {"authorized": True, "user": None, "phone": phone, "error": "Task sedang berjalan"}
            tasks.append(_fake())
        else:
            tasks.append(userbot.check_session(p))
    results = await asyncio.gather(*tasks)
    active_sessions = [res["phone"] for res in results if res["authorized"]]

    if not active_sessions:
        await event.respond(
            "⚠️ **Tidak ada akun aktif!**\nSemua session terputus. Silakan login kembali.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    buttons = []
    for phone in active_sessions:
        buttons.append([Button.inline(f"📱 Akun: {phone}", f"crg_sel_{phone}".encode('utf-8'))])
        
    buttons.append([Button.inline("🔙 Menu Utama", b"back_menu")])

    await event.respond(
        " megagroup 🏗️ **Buat Grup Otomatis — Pilih Akun**\n\n"
        "Pilih akun yang ingin Anda gunakan untuk membuat grup baru:",
        buttons=buttons,
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"crg_sel_")))
async def cb_create_group_account_selected(event):
    """Meminta nama grup dari admin."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("crg_sel_", "")
    await event.answer()

    if phone in active_tasks:
        await event.respond(
            f"⚠️ Akun `{phone}` sedang sibuk menjalankan task lain.\n"
            "Silakan tunggu hingga selesai atau pilih akun lain.",
            buttons=[[Button.inline("🔙 Kembali", b"menu_create_group")]],
            parse_mode="md"
        )
        return

    set_state(event.sender_id, STATE_AWAITING_GROUP_TITLE, phone=phone)
    await event.respond(
        f"🏗️ **Buat Grup Otomatis (Akun: `{phone}`)**\n\n"
        "Masukkan **Nama Grup** yang ingin dibuat:",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"cfm_crg_")))
async def cb_confirm_create_group(event):
    """Konfirmasi dan jalankan proses pembuatan grup di background."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("cfm_crg_", "")
    
    state = get_state(event.sender_id)
    if state != STATE_AWAITING_CONFIRM:
        await event.answer("⚠️ Sesi sudah kadaluarsa. Silakan mulai ulang.")
        return

    title = get_data(event.sender_id, "group_title")
    about = get_data(event.sender_id, "group_about", "")
    state_phone = get_data(event.sender_id, "phone")

    if phone != state_phone or not title:
        await event.respond("⚠️ Data tidak cocok atau tidak lengkap. Silakan mulai ulang.")
        clear_state(event.sender_id)
        return

    await event.answer("Membuat grup...")

    if phone in active_tasks:
        await event.respond(f"⚠️ Akun `{phone}` sedang menjalankan task lain.")
        clear_state(event.sender_id)
        return

    await event.respond(
        f"⏳ **Memulai pembuatan grup `{title}` pada akun `{phone}`...**\n"
        f"Proses berjalan di background. Anda akan menerima notifikasi jika selesai.",
        parse_mode="md",
    )

    task = asyncio.create_task(run_create_group_task(phone, title, about, event.sender_id))
    active_tasks[phone] = task

    clear_state(event.sender_id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: GENERATOR & VALIDATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_gen_val"))
async def cb_menu_gen_val(event):
    """Pilihan akun untuk validasi nomor generator."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    sessions = userbot.list_sessions()
    if not sessions:
        await event.respond(
            "⚠️ **Belum ada akun!**\nSilakan login akun terlebih dahulu.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    tasks = []
    for p in sessions:
        if p in active_tasks:
            async def _fake(phone=p):
                return {"authorized": True, "user": None, "phone": phone, "error": "Task sedang berjalan"}
            tasks.append(_fake())
        else:
            tasks.append(userbot.check_session(p))
    results = await asyncio.gather(*tasks)
    active_sessions = [res["phone"] for res in results if res["authorized"]]

    if not active_sessions:
        await event.respond(
            "⚠️ **Tidak ada akun aktif!**\nSemua session terputus. Silakan login kembali.",
            buttons=[[Button.inline("🔐 Login Akun", b"menu_login")]],
            parse_mode="md",
        )
        return

    buttons = []
    for phone in active_sessions:
        buttons.append([Button.inline(f"📱 Akun: {phone}", f"gen_val_sel_{phone}".encode('utf-8'))])
        
    buttons.append([Button.inline("🔙 Menu Utama", b"back_menu")])

    await event.respond(
        "🔢 **Generator & Validator Nomor — Pilih Akun**\n\n"
        "Pilih akun yang ingin Anda gunakan untuk memvalidasi nomor telepon hasil generator:",
        buttons=buttons,
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"gen_val_sel_")))
async def cb_gen_val_account_selected(event):
    """Meminta parameter generator dari admin."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("gen_val_sel_", "")
    await event.answer()

    if phone in active_tasks:
        await event.respond(
            f"⚠️ Akun `{phone}` sedang sibuk menjalankan task lain.\n"
            "Silakan tunggu hingga selesai atau pilih akun lain.",
            buttons=[[Button.inline("🔙 Kembali", b"menu_gen_val")]],
            parse_mode="md"
        )
        return

    set_state(event.sender_id, STATE_AWAITING_PREFIX_NAME, phone=phone)
    await event.respond(
        f"🔢 **Generator & Validator (Akun: `{phone}`)**\n\n"
        "Masukkan **Nama Prefix** kontak yang akan digunakan untuk menyimpan nomor valid:\n"
        "_(Contoh: `anjay` -> nama kontak akan disimpan menjadi `anjay(nomor)`)_",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


@bot.on(events.CallbackQuery(data=b"back_menu"))
async def cb_back_menu(event):
    """Kembali ke menu utama."""
    if not is_admin(event.sender_id):
        return
    await event.answer()
    clear_state(event.sender_id)
    await event.respond(WELCOME_TEXT, buttons=MAIN_BUTTONS, parse_mode="md")


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"cfm_val_")))
async def cb_confirm_validate(event):
    """Konfirmasi dan jalankan proses validasi nomor di background."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("cfm_val_", "")
    
    state = get_state(event.sender_id)
    if state != STATE_AWAITING_CONFIRM:
        await event.answer("⚠️ Sesi sudah kadaluarsa. Silakan mulai ulang.")
        return

    numbers = get_data(event.sender_id, "numbers")
    state_phone = get_data(event.sender_id, "phone")
    prefix_name = get_data(event.sender_id, "prefix_name", "prefix")
    csv_filename = get_data(event.sender_id, "csv_filename", "members.csv")

    if phone != state_phone or not numbers:
        await event.respond("⚠️ Data tidak cocok atau tidak lengkap. Silakan mulai ulang.")
        clear_state(event.sender_id)
        return

    await event.answer("Memulai validasi...")

    if phone in active_tasks:
        await event.respond(f"⚠️ Akun `{phone}` sedang menjalankan task lain.")
        clear_state(event.sender_id)
        return

    await event.respond(
        f"⏳ **Memulai proses validasi pada akun `{phone}`...**\n"
        f"Proses berjalan di background. Anda akan menerima notifikasi jika selesai.",
        parse_mode="md",
    )

    task = asyncio.create_task(run_validate_task(phone, numbers, event.sender_id, prefix_name, csv_filename))
    active_tasks[phone] = task

    clear_state(event.sender_id)


@bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"cfm_add_")))
async def cb_confirm_add(event):
    """Konfirmasi dan jalankan proses add member di background."""
    if not is_admin(event.sender_id):
        return

    phone = event.data.decode('utf-8').replace("cfm_add_", "")
    
    state = get_state(event.sender_id)
    if state != STATE_AWAITING_CONFIRM:
        await event.answer("⚠️ Sesi sudah kadaluarsa. Silakan mulai ulang.")
        return

    target = get_data(event.sender_id, "target_group")
    members = get_data(event.sender_id, "members")
    state_phone = get_data(event.sender_id, "phone")

    if phone != state_phone or not target or not members:
        await event.respond("⚠️ Data tidak cocok atau tidak lengkap. Silakan mulai ulang.")
        clear_state(event.sender_id)
        return

    await event.answer("Memulai proses...")

    if phone in active_tasks:
        await event.respond(f"⚠️ Akun `{phone}` sedang menjalankan task lain.")
        clear_state(event.sender_id)
        return

    await event.respond(
        f"⏳ **Memulai proses invite pada akun `{phone}`...**\n"
        f"Proses berjalan di background. Anda akan menerima notifikasi jika selesai.",
        parse_mode="md",
    )

    task = asyncio.create_task(run_add_task(phone, target, members, event.sender_id))
    active_tasks[phone] = task

    clear_state(event.sender_id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MESSAGE HANDLER: TEXT INPUT BERDASARKAN STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.message.text.startswith("/")))
async def handle_text_input(event):
    """
    Handler universal untuk input teks berdasarkan state user.
    Menangani: nomor telepon, OTP, 2FA password, source group, target group.
    """
    if not is_admin(event.sender_id):
        return

    state = get_state(event.sender_id)
    text = event.message.text.strip()

    # ── STATE: Menunggu Nomor Telepon ──
    if state == STATE_AWAITING_PHONE:
        phone = text
        if not phone.startswith("+") or len(phone) < 8:
            await event.respond(
                "❌ Format nomor tidak valid!\n\n"
                "Gunakan format internasional dengan `+` di depan.\n"
                "_Contoh: `+628123456789`_",
                parse_mode="md",
            )
            return

        await event.respond(f"⏳ Mengirim kode OTP ke `{phone}`...", parse_mode="md")

        result = await userbot.send_otp(phone)

        if result.get("already_logged_in"):
            me = result["user"]
            name = f"{me.first_name or ''} {me.last_name or ''}".strip()
            clear_state(event.sender_id)
            await event.respond(
                f"✅ **Sudah login!**\n\n"
                f"📱 Akun: `{phone}`\n"
                f"👤 Nama: **{name}**\n"
                f"🆔 Username: @{me.username or 'N/A'}\n"
                f"📱 ID: `{me.id}`",
                buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
                parse_mode="md",
            )
            return

        if not result["success"]:
            clear_state(event.sender_id)
            await event.respond(
                f"❌ **Gagal mengirim OTP!**\n\n{result['error']}",
                buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
                parse_mode="md",
            )
            return

        set_state(
            event.sender_id,
            STATE_AWAITING_OTP,
            phone=phone,
            phone_code_hash=result["phone_code_hash"],
        )

        await event.respond(
            "📱 **Kode OTP telah dikirim!**\n\n"
            "Cek aplikasi Telegram atau SMS Anda.\n"
            "Ketik kode OTP di sini:\n\n"
            "_Contoh: `12345`_",
            buttons=[[Button.inline("❌ Batal", b"menu_login")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu OTP ──
    if state == STATE_AWAITING_OTP:
        phone = get_data(event.sender_id, "phone")
        phone_code_hash = get_data(event.sender_id, "phone_code_hash")
        await event.respond("⏳ Memverifikasi kode OTP...")

        result = await userbot.verify_otp(phone, text, phone_code_hash)

        if result["needs_2fa"]:
            set_state(event.sender_id, STATE_AWAITING_2FA, phone=phone)
            await event.respond(
                "🔐 **Verifikasi Dua Langkah (2FA)**\n\n"
                "Akun ini memiliki 2FA. Kirim password Anda:",
                buttons=[[Button.inline("❌ Batal", b"menu_login")]],
                parse_mode="md",
            )
            return

        if not result["success"]:
            await event.respond(
                f"❌ {result['error']}\n\nKirim ulang kode OTP yang benar:",
                parse_mode="md",
            )
            return

        me = result["user"]
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        clear_state(event.sender_id)
        await event.respond(
            f"✅ **Login Berhasil!**\n\n"
            f"📱 Akun: `{phone}`\n"
            f"👤 Nama: **{name}**\n"
            f"🆔 Username: @{me.username or 'N/A'}\n"
            f"📱 ID: `{me.id}`\n\n"
            f"Session telah disimpan.",
            buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu 2FA Password ──
    if state == STATE_AWAITING_2FA:
        phone = get_data(event.sender_id, "phone")
        await event.respond("⏳ Memverifikasi password 2FA...")

        result = await userbot.verify_2fa(phone, text)

        if not result["success"]:
            await event.respond(
                f"❌ {result['error']}\n\nCoba kirim password lagi:",
                parse_mode="md",
            )
            return

        me = result["user"]
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        clear_state(event.sender_id)
        await event.respond(
            f"✅ **Login Berhasil!** (dengan 2FA)\n\n"
            f"📱 Akun: `{phone}`\n"
            f"👤 Nama: **{name}**\n"
            f"🆔 Username: @{me.username or 'N/A'}\n"
            f"📱 ID: `{me.id}`",
            buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Source Group (Scrape) ──
    if state == STATE_AWAITING_SOURCE_GROUP:
        phone = get_data(event.sender_id, "phone")
        if not phone:
            await event.respond("❌ Nomor telepon tidak ditemukan. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        if phone in active_tasks:
            await event.respond(f"⚠️ Akun `{phone}` sedang sibuk menjalankan task lain.")
            clear_state(event.sender_id)
            return

        set_state(event.sender_id, STATE_AWAITING_SCR_CSV_FILENAME, phone=phone, source_group=text)
        await event.respond(
            f"📋 **Scrape Member (Akun: `{phone}`)**\n"
            f"Grup Sumber: `{text}`\n\n"
            "Masukkan **Nama File CSV** untuk menyimpan hasil scrape (tanpa `.csv`):\n"
            "_(Contoh: `grup_a` -> disimpan sebagai `grup_a.csv`)_\n\n"
            "Ketik `members` atau langsung kirim teks untuk menggunakan file default (`members.csv`):",
            buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Nama File CSV (Scrape Grup) ──
    if state == STATE_AWAITING_SCR_CSV_FILENAME:
        phone = get_data(event.sender_id, "phone")
        source_group = get_data(event.sender_id, "source_group")
        if not phone or not source_group:
            await event.respond("❌ Data sesi tidak lengkap. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        csv_filename = sanitize_csv_filename(text.strip())

        await event.respond(
            f"⏳ **Memulai scrape grup pada akun `{phone}`...**\n"
            f"Hasil akan disimpan ke file `{csv_filename}`.\n"
            "Proses berjalan di background. Anda akan menerima notifikasi jika selesai.",
            parse_mode="md"
        )

        task = asyncio.create_task(run_scrape_task(phone, source_group, event.sender_id, csv_filename=csv_filename))
        active_tasks[phone] = task
        
        clear_state(event.sender_id)
        return

    # ── STATE: Menunggu Nama File CSV (Scrape Kontak) ──
    if state == STATE_AWAITING_CNT_CSV_FILENAME:
        phone = get_data(event.sender_id, "phone")
        if not phone:
            await event.respond("❌ Nomor telepon tidak ditemukan. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        csv_filename = sanitize_csv_filename(text.strip())

        await event.respond(
            f"⏳ **Memulai scraping kontak pada akun `{phone}`...**\n"
            f"Hasil akan disimpan ke file `{csv_filename}`.\n"
            "Proses berjalan di background. Anda akan menerima notifikasi jika selesai.",
            parse_mode="md",
        )

        task = asyncio.create_task(run_scrape_contacts_task(phone, event.sender_id, csv_filename=csv_filename))
        active_tasks[phone] = task
        
        clear_state(event.sender_id)
        return

    # ── STATE: Menunggu Target Group (Add) ──
    if state == STATE_AWAITING_TARGET_GROUP:
        phone = get_data(event.sender_id, "phone")
        source_type = get_data(event.sender_id, "source_type")
        csv_filename = get_data(event.sender_id, "csv_filename", "members.csv")

        if not phone:
            await event.respond("❌ Sesi tidak lengkap. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        await event.respond("⏳ Mencari grup target...")

        info = await userbot.resolve_group(phone, text)

        if not info["success"]:
            await event.respond(
                f"❌ Grup tidak ditemukan!\n{info['error']}\n\nCoba kirim ulang:",
                parse_mode="md",
            )
            return

        if source_type == "contacts":
            await event.respond("⏳ Mengambil daftar kontak secara real-time dari akun...")
            contacts_res = await userbot.get_contacts_list(phone)
            if not contacts_res["success"]:
                await event.respond(
                    f"❌ Gagal mengambil kontak!\n{contacts_res['error']}\n\nSilakan mulai ulang.",
                    buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
                    parse_mode="md"
                )
                clear_state(event.sender_id)
                return
            members = contacts_res["contacts"]
            if not members:
                await event.respond(
                    "❌ Akun ini tidak memiliki daftar kontak untuk di-invite.\n\nSilakan mulai ulang.",
                    buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
                    parse_mode="md"
                )
                clear_state(event.sender_id)
                return
        else:
            members = get_data(event.sender_id, "members")
            if not members:
                await event.respond("❌ Data member kosong. Silakan mulai ulang.")
                clear_state(event.sender_id)
                return

        set_state(
            event.sender_id,
            STATE_AWAITING_CONFIRM,
            phone=phone,
            target_group=text,
            members=members,
            csv_filename=csv_filename,
        )

        confirm_callback = f"cfm_add_{phone}".encode('utf-8')

        await event.respond(
            f"🎯 **Konfirmasi Add Member**\n"
            f"📱 Akun: `{phone}`\n"
            f"🔌 Sumber: **{ f'CSV ({csv_filename})' if source_type == 'csv' else 'Kontak Langsung' }**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 Grup target: **{info['title']}**\n"
            f"👥 Jumlah member: **{len(members)}**\n"
            f"⏱️ Delay: **15-45 detik** per invite\n"
            f"🛡️ Batas per sesi: **50 member**\n\n"
            f"Lanjutkan?",
            buttons=[
                [
                    Button.inline("✅ Ya, Mulai!", confirm_callback),
                    Button.inline("❌ Batal", b"menu_cancel"),
                ],
            ],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Nama Prefix ──
    if state == STATE_AWAITING_PREFIX_NAME:
        phone = get_data(event.sender_id, "phone")
        if not phone:
            await event.respond("❌ Nomor telepon tidak ditemukan. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        prefix_name = text.strip()
        if not prefix_name:
            await event.respond("❌ Nama prefix tidak boleh kosong! Silakan masukkan nama prefix:")
            return

        set_state(event.sender_id, STATE_AWAITING_BASE_NUMBER, prefix_name=prefix_name)
        await event.respond(
            f"🔢 **Generator & Validator (Akun: `{phone}`)**\n"
            f"Prefix Kontak: `{prefix_name}`\n\n"
            "Kirim **Nomor Telepon Awal** untuk di-generate:\n"
            "_(Contoh: `+6281234567890`)_",
            buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Nomor Telepon Awal (Base Number) ──
    if state == STATE_AWAITING_BASE_NUMBER:
        phone = get_data(event.sender_id, "phone")
        prefix_name = get_data(event.sender_id, "prefix_name")
        if not phone or not prefix_name:
            await event.respond("❌ Data sesi tidak lengkap. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        base_number = text.replace(" ", "").replace("-", "")
        if base_number.startswith("0"):
            await event.respond(
                "❌ **Format Salah!** Nomor tidak boleh diawali dengan `0`.\n"
                "Harap masukkan nomor dengan **kode negara** (format internasional).\n\n"
                "_Contoh:_\n"
                "• `+6281234567890` (Indonesia)\n"
                "• `+966555018815` (Arab Saudi)\n\n"
                "Kirim ulang nomor telepon awal Anda:",
                parse_mode="md",
            )
            return
        elif not base_number.startswith("+"):
            base_number = "+" + base_number

        # Validasi base number: harus memiliki minimal beberapa digit setelah pembersihan
        digits_only = "".join(c for c in base_number if c.isdigit())
        if len(digits_only) < 7:
            await event.respond(
                "❌ Format nomor awal tidak valid! Minimal 7 digit.\n"
                "Harap kirim ulang nomor telepon awal dengan benar (contoh: `+6281234567890`):",
                parse_mode="md",
            )
            return

        set_state(event.sender_id, STATE_AWAITING_GEN_COUNT, base_number=base_number)
        await event.respond(
            f"🔢 **Generator & Validator (Akun: `{phone}`)**\n"
            f"Prefix Kontak: `{prefix_name}`\n"
            f"Nomor Awal: `{base_number}`\n\n"
            "Masukkan **Jumlah Nomor** yang ingin di-generate (maksimal 2500):",
            buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Jumlah Nomor (Gen Count) ──
    if state == STATE_AWAITING_GEN_COUNT:
        phone = get_data(event.sender_id, "phone")
        prefix_name = get_data(event.sender_id, "prefix_name")
        base_number = get_data(event.sender_id, "base_number")
        if not phone or not prefix_name or not base_number:
            await event.respond("❌ Data sesi tidak lengkap. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        if not text.isdigit():
            await event.respond("❌ Jumlah nomor harus berupa angka positif! Coba lagi:")
            return

        count = int(text)
        if count < 1 or count > 2500:
            await event.respond("❌ Jumlah nomor harus di antara 1 s/d 2500! Coba lagi:")
            return

        set_state(event.sender_id, STATE_AWAITING_VAL_CSV_FILENAME, count=count)
        await event.respond(
            f"🔢 **Generator & Validator (Akun: `{phone}`)**\n"
            f"Prefix Kontak: `{prefix_name}`\n"
            f"Nomor Awal: `{base_number}`\n"
            f"Jumlah: `{count}` nomor\n\n"
            "Masukkan **Nama File CSV** untuk menyimpan hasil validasi nomor (tanpa `.csv`):\n"
            "_(Contoh: `nomor_valid` -> disimpan sebagai `nomor_valid.csv`)_\n\n"
            "Ketik `members` atau langsung kirim teks untuk menggunakan file default (`members.csv`):",
            buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Nama File CSV (Validation) ──
    if state == STATE_AWAITING_VAL_CSV_FILENAME:
        phone = get_data(event.sender_id, "phone")
        prefix_name = get_data(event.sender_id, "prefix_name")
        base_number = get_data(event.sender_id, "base_number")
        count = get_data(event.sender_id, "count")
        if not phone or not prefix_name or not base_number or not count:
            await event.respond("❌ Data sesi tidak lengkap. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        csv_filename = sanitize_csv_filename(text.strip())

        await event.respond("⏳ Men-generate nomor telepon...")

        generated_numbers = userbot.generate_phone_numbers(base_number, count)
        if not generated_numbers:
            await event.respond("❌ Gagal men-generate nomor. Pastikan format nomor awal benar. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        first_num = generated_numbers[0]
        last_num = generated_numbers[-1]

        set_state(
            event.sender_id,
            STATE_AWAITING_CONFIRM,
            phone=phone,
            prefix_name=prefix_name,
            base_number=base_number,
            numbers=generated_numbers,
            source_type="validation",
            csv_filename=csv_filename,
        )

        confirm_callback = f"cfm_val_{phone}".encode('utf-8')

        await event.respond(
            f"🔢 **Konfirmasi Validasi Nomor**\n"
            f"📱 Akun: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Prefix Kontak: **{prefix_name}**\n"
            f"• Rentang Nomor: **{first_num}** s/d **{last_num}**\n"
            f"• Total di-generate: **{len(generated_numbers)}** nomor\n"
            f"• File Target: **{csv_filename}**\n\n"
            f"Apakah Anda ingin mulai memvalidasi nomor-nomor ini di Telegram?\n"
            f"Nomor yang valid akan disimpan ke kontak dengan format **{prefix_name}(nomor)** dan diekspor ke `{csv_filename}` agar langsung siap di-invite.",
            buttons=[
                [
                    Button.inline("✅ Ya, Mulai Validasi!", confirm_callback),
                    Button.inline("❌ Batal", b"menu_cancel"),
                ],
            ],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Nama Grup (Auto Create Group) ──
    if state == STATE_AWAITING_GROUP_TITLE:
        phone = get_data(event.sender_id, "phone")
        if not phone:
            await event.respond("❌ Nomor telepon tidak ditemukan. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        title = text.strip()
        if not title:
            await event.respond("❌ Nama grup tidak boleh kosong! Silakan masukkan nama grup:")
            return

        set_state(event.sender_id, STATE_AWAITING_GROUP_ABOUT, phone=phone, group_title=title)
        await event.respond(
            f"🏗️ **Buat Grup Otomatis (Akun: `{phone}`)**\n"
            f"Nama Grup: `{title}`\n\n"
            "Masukkan **Deskripsi Grup** (atau ketik `/skip` untuk mengosongkan):",
            buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Deskripsi Grup (Auto Create Group) ──
    if state == STATE_AWAITING_GROUP_ABOUT:
        phone = get_data(event.sender_id, "phone")
        title = get_data(event.sender_id, "group_title")
        if not phone or not title:
            await event.respond("❌ Data sesi tidak lengkap. Silakan mulai ulang.")
            clear_state(event.sender_id)
            return

        about = text.strip()
        if about.lower() == "/skip":
            about = ""

        set_state(
            event.sender_id,
            STATE_AWAITING_CONFIRM,
            phone=phone,
            group_title=title,
            group_about=about,
        )

        confirm_callback = f"cfm_crg_{phone}".encode('utf-8')

        await event.respond(
            f"🏗️ **Konfirmasi Buat Grup**\n"
            f"📱 Akun: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"• Nama Grup: **{title}**\n"
            f"• Deskripsi: **{about or '(Kosong)'}**\n\n"
            f"Apakah Anda ingin membuat grup ini sekarang?",
            buttons=[
                [
                    Button.inline("✅ Ya, Buat Grup!", confirm_callback),
                    Button.inline("❌ Batal", b"menu_cancel"),
                ],
            ],
            parse_mode="md",
        )
        return






    # ── STATE IDLE: Tidak ada operasi aktif ──
    if state == STATE_IDLE:
        await event.respond(
            "💡 Ketik /start atau /menu untuk membuka menu.",
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    """Start bot."""
    print()
    print("=" * 50)
    print("  🤖 Telegram Add Member Bot — Starting...")
    print("=" * 50)
    print()

    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    print(f"  ✅ Bot aktif: @{me.username}")
    print(f"  👤 Admin ID: {ADMIN_ID}")
    print(f"  📁 Sessions: {SESSIONS_DIR}")
    print()
    print("  Kirim /start ke bot untuk memulai.")
    print("  Tekan Ctrl+C untuk menghentikan bot.")
    print()

    logger.info(f"Bot started: @{me.username}")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
