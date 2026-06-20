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
    SESSIONS_DIR,
    logger,
)
from src import userbot


# ── State Machine ──
# Menyimpan state percakapan per user
user_state = {}

# State constants
STATE_IDLE = "idle"
STATE_AWAITING_PHONE = "awaiting_phone"
STATE_AWAITING_OTP = "awaiting_otp"
STATE_AWAITING_2FA = "awaiting_2fa"
STATE_AWAITING_SOURCE_GROUP = "awaiting_source_group"
STATE_AWAITING_TARGET_GROUP = "awaiting_target_group"
STATE_AWAITING_CONFIRM = "awaiting_confirm"
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

@bot.on(events.CallbackQuery(data=b"menu_login"))
async def cb_login(event):
    """Memulai proses login — cek session lama dulu, lalu minta nomor telepon."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    # Cek apakah sudah ada session yang valid
    session = await userbot.check_session()
    if session["authorized"]:
        me = session["user"]
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        await event.respond(
            f"✅ **Sudah login!**\n\n"
            f"👤 Nama: **{name}**\n"
            f"🆔 Username: @{me.username or 'N/A'}\n"
            f"📱 ID: `{me.id}`",
            buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
            parse_mode="md",
        )
        return

    # Belum login → minta nomor telepon
    set_state(event.sender_id, STATE_AWAITING_PHONE)
    await event.respond(
        "🔐 **Login Akun Telegram**\n\n"
        "Kirim **nomor telepon** akun yang ingin digunakan:\n\n"
        "_Contoh: `+628123456789`_",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: MENU SCRAPE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_scrape"))
async def cb_scrape(event):
    """Memulai proses scraping."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    # Cek session dulu
    session = await userbot.check_session()
    if not session["authorized"]:
        await event.respond(
            "⚠️ **Belum login!**\nGunakan menu Login terlebih dahulu.",
            buttons=[[Button.inline("🔐 Login", b"menu_login")]],
            parse_mode="md",
        )
        return

    set_state(event.sender_id, STATE_AWAITING_SOURCE_GROUP)
    await event.respond(
        "📋 **Scrape Member**\n\n"
        "Kirim username atau link **grup sumber** yang ingin di-scrape:\n\n"
        "_Contoh:_\n"
        "• `@nama_grup`\n"
        "• `https://t.me/nama_grup`\n"
        "• `-100123456789`",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: MENU ADD MEMBER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_add"))
async def cb_add(event):
    """Memulai proses add member."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    # Cek session
    session = await userbot.check_session()
    if not session["authorized"]:
        await event.respond(
            "⚠️ **Belum login!**\nGunakan menu Login terlebih dahulu.",
            buttons=[[Button.inline("🔐 Login", b"menu_login")]],
            parse_mode="md",
        )
        return

    # Cek CSV
    members = userbot.load_members()
    if not members:
        await event.respond(
            "⚠️ **Data member kosong!**\n"
            "Lakukan Scrape terlebih dahulu untuk mengisi data.",
            buttons=[
                [Button.inline("📋 Scrape Member", b"menu_scrape")],
                [Button.inline("🔙 Menu Utama", b"back_menu")],
            ],
            parse_mode="md",
        )
        return

    set_state(event.sender_id, STATE_AWAITING_TARGET_GROUP, members=members)
    await event.respond(
        f"➕ **Add Member**\n\n"
        f"📊 Data tersedia: **{len(members)} member**\n\n"
        f"Kirim username atau link **grup target**:\n\n"
        f"_Contoh:_\n"
        f"• `@grup_target`\n"
        f"• `https://t.me/grup_target`",
        buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
        parse_mode="md",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: STATUS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_status"))
async def cb_status(event):
    """Menampilkan status akun dan data."""
    if not is_admin(event.sender_id):
        return

    await event.answer()

    # Cek session
    session = await userbot.check_session()
    if session["authorized"]:
        me = session["user"]
        name = f"{me.first_name or ''} {me.last_name or ''}".strip()
        login_status = f"✅ Login sebagai **{name}** (@{me.username or 'N/A'})"
    else:
        login_status = "❌ Belum login"

    # Cek CSV
    members = userbot.load_members()
    csv_status = f"📊 **{len(members)} member** tersimpan" if members else "📊 Belum ada data member"

    await event.respond(
        f"📊 **Status Tool**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔐 Akun: {login_status}\n"
        f"{csv_status}\n",
        buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
        parse_mode="md",
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: CANCEL & BACK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"menu_cancel"))
async def cb_cancel(event):
    """Batalkan operasi dan kembali ke menu."""
    if not is_admin(event.sender_id):
        return
    await event.answer("Dibatalkan")
    clear_state(event.sender_id)
    await event.respond(
        "❌ Operasi dibatalkan.\n",
        buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
    )


@bot.on(events.CallbackQuery(data=b"back_menu"))
async def cb_back_menu(event):
    """Kembali ke menu utama."""
    if not is_admin(event.sender_id):
        return
    await event.answer()
    clear_state(event.sender_id)
    await event.respond(WELCOME_TEXT, buttons=MAIN_BUTTONS, parse_mode="md")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CALLBACK: CONFIRM ADD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@bot.on(events.CallbackQuery(data=b"confirm_add"))
async def cb_confirm_add(event):
    """Konfirmasi dan mulai proses add member."""
    if not is_admin(event.sender_id):
        return

    await event.answer("Memulai proses...")
    state = get_state(event.sender_id)
    if state != STATE_AWAITING_CONFIRM:
        await event.respond("⚠️ Sesi sudah kadaluarsa. Silakan mulai ulang.")
        return

    target = get_data(event.sender_id, "target_group")
    members = get_data(event.sender_id, "members")

    if not target or not members:
        await event.respond("⚠️ Data tidak lengkap. Silakan mulai ulang.")
        clear_state(event.sender_id)
        return

    set_state(event.sender_id, STATE_BUSY)

    await event.respond(
        "⏳ **Memulai proses invite...**\n"
        "Ini akan memakan waktu. Anda akan mendapat update progress.",
        parse_mode="md",
    )

    # Callback untuk update progress
    async def on_progress(msg):
        try:
            await bot.send_message(event.sender_id, msg, parse_mode="md")
        except Exception:
            pass

    # Jalankan proses add member
    result = await userbot.add_members(target, members, progress_callback=on_progress)

    clear_state(event.sender_id)

    if not result["success"]:
        await event.respond(
            f"❌ **Gagal!**\n{result['error']}",
            buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
            parse_mode="md",
        )
        return

    # Laporan akhir
    report = (
        f"📊 **LAPORAN AKHIR**\n"
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

    await event.respond(
        report,
        buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
        parse_mode="md",
    )


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
        # Validasi format sederhana
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

        # OTP terkirim — simpan phone & hash, tunggu input OTP
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
            buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
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
                buttons=[[Button.inline("❌ Batal", b"menu_cancel")]],
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
            f"👤 Nama: **{name}**\n"
            f"🆔 Username: @{me.username or 'N/A'}\n"
            f"📱 ID: `{me.id}`",
            buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Source Group (Scrape) ──
    if state == STATE_AWAITING_SOURCE_GROUP:
        set_state(event.sender_id, STATE_BUSY)
        await event.respond("⏳ Memulai scraping...", parse_mode="md")

        async def on_progress(progress_msg):
            try:
                await bot.send_message(event.sender_id, progress_msg, parse_mode="md")
            except Exception:
                pass

        result = await userbot.scrape_members(text, progress_callback=on_progress)
        clear_state(event.sender_id)

        if not result["success"]:
            await event.respond(
                f"❌ **Scrape Gagal!**\n\n{result['error']}",
                buttons=[[Button.inline("🔙 Menu Utama", b"back_menu")]],
                parse_mode="md",
            )
            return

        await event.respond(
            f"✅ **Scrape Berhasil!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 Grup: **{result['group_title']}**\n"
            f"👥 Total ditemukan: **{result['total']}**\n"
            f"💾 Tersimpan: **{result['saved']}** member\n"
            f"🤖 Bot dilewati: **{result['skipped_bots']}**\n"
            f"💀 Akun terhapus: **{result['skipped_deleted']}**\n\n"
            f"Data disimpan ke `members.csv`",
            buttons=[
                [Button.inline("➕ Lanjut Add Member", b"menu_add")],
                [Button.inline("🔙 Menu Utama", b"back_menu")],
            ],
            parse_mode="md",
        )
        return

    # ── STATE: Menunggu Target Group (Add) ──
    if state == STATE_AWAITING_TARGET_GROUP:
        await event.respond("⏳ Mencari grup target...")

        info = await userbot.resolve_group(text)

        if not info["success"]:
            await event.respond(
                f"❌ Grup tidak ditemukan!\n{info['error']}\n\nCoba kirim ulang:",
                parse_mode="md",
            )
            return

        members = get_data(event.sender_id, "members")
        set_state(
            event.sender_id,
            STATE_AWAITING_CONFIRM,
            target_group=text,
            members=members,
        )

        await event.respond(
            f"🎯 **Konfirmasi Add Member**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 Grup target: **{info['title']}**\n"
            f"👥 Jumlah member: **{len(members)}**\n"
            f"⏱️ Delay: **15-45 detik** per invite\n"
            f"🛡️ Batas per sesi: **50 member**\n\n"
            f"Lanjutkan?",
            buttons=[
                [
                    Button.inline("✅ Ya, Mulai!", b"confirm_add"),
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
