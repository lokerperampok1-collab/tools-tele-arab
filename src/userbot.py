"""
userbot.py — Operasi Userbot (Login, Scrape, Add)
====================================================
Modul ini berisi fungsi-fungsi async murni untuk operasi
Telegram menggunakan akun pengguna (userbot). Digunakan
oleh bot.py sebagai backend — BUKAN untuk dijalankan langsung.

Semua data sensitif (nomor telepon, password 2FA) diterima
sebagai parameter fungsi, BUKAN dari environment variable.
"""

import asyncio
import csv
import random
import time
from pathlib import Path
from typing import Callable, Optional

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    ApiIdInvalidError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    UserNotMutualContactError,
    UserChannelsTooMuchError,
    ChatWriteForbiddenError,
    FloodWaitError,
    UserAlreadyParticipantError,
    UserKickedError,
    UserBannedInChannelError,
    InputUserDeactivatedError,
)
from telethon.tl.functions.channels import (
    GetParticipantsRequest,
    InviteToChannelRequest,
)
from telethon.tl.types import (
    ChannelParticipantsSearch,
    InputPeerUser,
)

from src import (
    API_ID,
    API_HASH,
    MEMBERS_CSV,
    SESSIONS_DIR,
    get_session_path,
    logger,
)


# ── Rate Limiting Config ──
MIN_DELAY = 15
MAX_DELAY = 45
MAX_ADDS_PER_SESSION = 50
FLOOD_WAIT_BUFFER = 10


def get_client(phone: str) -> TelegramClient:
    """Membuat instance TelegramClient berdasarkan nomor telepon."""
    return TelegramClient(get_session_path(phone), API_ID, API_HASH)


def list_sessions() -> list[str]:
    """Mengembalikan daftar nomor telepon yang memiliki session tersimpan."""
    sessions = []
    for f in SESSIONS_DIR.glob("*.session"):
        sessions.append(f.stem)
    return sessions


def get_active_phone() -> Optional[str]:
    """
    Mengembalikan nomor telepon dari session yang pertama ditemukan.
    Digunakan untuk operasi scrape/add yang membutuhkan client.
    Returns None jika belum ada session.
    """
    sessions = list_sessions()
    return sessions[0] if sessions else None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LOGIN OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def check_session() -> dict:
    """
    Mengecek apakah ada session yang masih valid.

    Returns:
        dict: {"authorized": bool, "user": User|None, "phone": str|None, "error": str|None}
    """
    phone = get_active_phone()
    if not phone:
        return {"authorized": False, "user": None, "phone": None, "error": None}

    client = get_client(phone)
    try:
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            return {"authorized": True, "user": me, "phone": phone, "error": None}
        return {"authorized": False, "user": None, "phone": phone, "error": None}
    except Exception as e:
        return {"authorized": False, "user": None, "phone": phone, "error": str(e)}
    finally:
        await client.disconnect()


async def send_otp(phone: str) -> dict:
    """
    Mengirim kode OTP ke nomor telepon yang diberikan.

    Args:
        phone: Nomor telepon (contoh: +628123456789)

    Returns:
        dict dengan status pengiriman OTP.
    """
    client = get_client(phone)
    try:
        await client.connect()

        # Cek apakah sudah login
        if await client.is_user_authorized():
            me = await client.get_me()
            return {
                "success": True,
                "phone_code_hash": None,
                "error": None,
                "already_logged_in": True,
                "user": me,
            }

        result = await client.send_code_request(phone)
        return {
            "success": True,
            "phone_code_hash": result.phone_code_hash,
            "error": None,
            "already_logged_in": False,
            "user": None,
        }
    except PhoneNumberInvalidError:
        return {
            "success": False,
            "phone_code_hash": None,
            "error": f"Nomor telepon tidak valid: {phone}",
        }
    except ApiIdInvalidError:
        return {
            "success": False,
            "phone_code_hash": None,
            "error": "API_ID atau API_HASH tidak valid!",
        }
    except Exception as e:
        return {
            "success": False,
            "phone_code_hash": None,
            "error": f"Gagal mengirim OTP: {type(e).__name__}: {e}",
        }
    finally:
        await client.disconnect()


async def verify_otp(phone: str, otp_code: str, phone_code_hash: str) -> dict:
    """
    Memverifikasi kode OTP dan menyelesaikan login.

    Args:
        phone: Nomor telepon.
        otp_code: Kode OTP dari user.
        phone_code_hash: Hash dari send_code_request.

    Returns:
        dict dengan status verifikasi.
    """
    client = get_client(phone)
    try:
        await client.connect()

        await client.sign_in(
            phone=phone,
            code=otp_code,
            phone_code_hash=phone_code_hash,
        )

        me = await client.get_me()
        return {"success": True, "needs_2fa": False, "user": me, "error": None}

    except PhoneCodeInvalidError:
        return {
            "success": False,
            "needs_2fa": False,
            "user": None,
            "error": "Kode OTP salah! Coba lagi.",
        }
    except SessionPasswordNeededError:
        return {
            "success": False,
            "needs_2fa": True,
            "user": None,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "needs_2fa": False,
            "user": None,
            "error": f"Login gagal: {type(e).__name__}: {e}",
        }
    finally:
        await client.disconnect()


async def verify_2fa(phone: str, password: str) -> dict:
    """
    Memverifikasi password 2FA.

    Args:
        phone: Nomor telepon (untuk load session yang benar).
        password: Password verifikasi dua langkah.

    Returns:
        dict dengan status verifikasi.
    """
    client = get_client(phone)
    try:
        await client.connect()
        await client.sign_in(password=password)
        me = await client.get_me()
        return {"success": True, "user": me, "error": None}
    except Exception as e:
        return {
            "success": False,
            "user": None,
            "error": f"Password 2FA salah: {type(e).__name__}: {e}",
        }
    finally:
        await client.disconnect()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SCRAPE OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def scrape_members(
    source_group_input: str,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Scrape member dari grup sumber dan simpan ke CSV.

    Args:
        source_group_input: Username/link/ID grup sumber.
        progress_callback: Async callback(message) untuk update progress.

    Returns:
        dict dengan hasil scraping.
    """
    phone = get_active_phone()
    if not phone:
        return {"success": False, "error": "Belum ada session! Login terlebih dahulu."}

    client = get_client(phone)

    async def _progress(msg):
        if progress_callback:
            await progress_callback(msg)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "error": "Session expired! Login ulang."}

        # Resolve group entity
        await _progress("🔍 Mencari grup...")
        try:
            source_group = await client.get_entity(source_group_input)
        except (ValueError, Exception) as e:
            return {
                "success": False,
                "error": f"Grup tidak ditemukan: {source_group_input}\n{e}",
            }

        group_title = getattr(source_group, "title", source_group_input)
        await _progress(f"✅ Grup ditemukan: {group_title}\n⏳ Mengambil daftar member...")

        # Fetch participants
        all_participants = []
        offset = 0
        batch_size = 200

        while True:
            try:
                participants = await client(
                    GetParticipantsRequest(
                        channel=source_group,
                        filter=ChannelParticipantsSearch(""),
                        offset=offset,
                        limit=batch_size,
                        hash=0,
                    )
                )
            except Exception as e:
                logger.error(f"Error fetching participants at offset {offset}: {e}")
                break

            if not participants.users:
                break

            all_participants.extend(participants.users)
            offset += len(participants.users)

            if offset % 400 == 0:
                await _progress(f"📥 {offset} member diambil...")

            if len(participants.users) < batch_size:
                break

        # Filter
        filtered = []
        skipped_bots = 0
        skipped_deleted = 0

        for user in all_participants:
            if user.bot:
                skipped_bots += 1
                continue
            if user.deleted:
                skipped_deleted += 1
                continue

            filtered.append({
                "user_id": user.id,
                "access_hash": user.access_hash,
                "username": user.username or "",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
            })

        if not filtered:
            return {
                "success": False,
                "error": "Tidak ada member valid yang bisa disimpan.",
            }

        # Save CSV
        with open(MEMBERS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["user_id", "access_hash", "username", "first_name", "last_name"],
            )
            writer.writeheader()
            writer.writerows(filtered)

        logger.info(f"Scraped {len(filtered)} members from {group_title}")

        return {
            "success": True,
            "total": len(all_participants),
            "saved": len(filtered),
            "skipped_bots": skipped_bots,
            "skipped_deleted": skipped_deleted,
            "group_title": group_title,
            "error": None,
        }

    except Exception as e:
        return {"success": False, "error": f"Error: {type(e).__name__}: {e}"}
    finally:
        await client.disconnect()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ADD MEMBER OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def load_members() -> list[dict]:
    """Membaca data member dari CSV. Mengembalikan list kosong jika file tidak ada."""
    if not MEMBERS_CSV.exists():
        return []
    members = []
    with open(MEMBERS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            members.append(row)
    return members


async def resolve_group(group_input: str) -> dict:
    """
    Resolve nama grup target dan kembalikan info.

    Returns:
        dict: {"success": bool, "title": str, "error": str|None}
    """
    phone = get_active_phone()
    if not phone:
        return {"success": False, "title": "", "error": "Belum ada session!"}

    client = get_client(phone)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "title": "", "error": "Session expired!"}

        entity = await client.get_entity(group_input)
        title = getattr(entity, "title", group_input)
        return {"success": True, "title": title, "error": None}
    except (ValueError, Exception) as e:
        return {"success": False, "title": "", "error": str(e)}
    finally:
        await client.disconnect()


async def add_members(
    target_group_input: str,
    members: list[dict],
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Menambahkan member ke grup target dengan rate limiting dan error handling.

    Args:
        target_group_input: Username/link/ID grup target.
        members: List of dict dari CSV.
        progress_callback: Async callback(message) untuk update progress.

    Returns:
        dict hasil akhir dengan statistik.
    """
    phone = get_active_phone()
    if not phone:
        return {"success": False, "error": "Belum ada session!"}

    client = get_client(phone)

    async def _progress(msg):
        if progress_callback:
            await progress_callback(msg)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "error": "Session expired! Login ulang."}

        # Resolve target group
        try:
            target_group = await client.get_entity(target_group_input)
        except Exception as e:
            return {"success": False, "error": f"Grup target tidak ditemukan: {e}"}

        group_title = getattr(target_group, "title", target_group_input)
        await _progress(f"🎯 Target: **{group_title}**\n⏳ Memulai proses invite...\n")

        added = 0
        skipped = 0
        failed = 0
        start_time = time.time()
        stopped_reason = None

        for idx, member in enumerate(members, start=1):
            # Batas per sesi
            if added >= MAX_ADDS_PER_SESSION:
                stopped_reason = f"Batas per sesi tercapai ({MAX_ADDS_PER_SESSION})"
                break

            uid = member.get("user_id", "")
            ahash = member.get("access_hash", "")
            uname = member.get("username", "")
            name = f"{member.get('first_name', '')} {member.get('last_name', '')}".strip()
            display = f"{name} (@{uname})" if uname else f"{name} (ID:{uid})"

            if not uid or not ahash:
                skipped += 1
                continue

            try:
                user_peer = InputPeerUser(user_id=int(uid), access_hash=int(ahash))
                await client(InviteToChannelRequest(target_group, [user_peer]))
                added += 1
                logger.info(f"Added: {display}")

                # Update progress setiap 5 member atau yang pertama
                if added == 1 or added % 5 == 0:
                    await _progress(
                        f"📊 Progress: {idx}/{len(members)}\n"
                        f"✅ Ditambahkan: {added} | ⏩ Skip: {skipped} | ❌ Gagal: {failed}"
                    )

            except UserAlreadyParticipantError:
                skipped += 1
                logger.info(f"Already member: {display}")

            except UserPrivacyRestrictedError:
                skipped += 1
                logger.info(f"Privacy restricted: {display}")

            except UserNotMutualContactError:
                skipped += 1
                logger.info(f"Not mutual contact: {display}")

            except UserChannelsTooMuchError:
                skipped += 1
                logger.info(f"Too many channels: {display}")

            except UserKickedError:
                skipped += 1
                logger.info(f"User was kicked: {display}")

            except UserBannedInChannelError:
                skipped += 1
                logger.info(f"User banned: {display}")

            except InputUserDeactivatedError:
                skipped += 1
                logger.info(f"Deactivated account: {display}")

            except ChatWriteForbiddenError:
                stopped_reason = "Akun tidak punya izin invite di grup target!"
                failed += 1
                break

            except FloodWaitError as e:
                wait_sec = e.seconds + FLOOD_WAIT_BUFFER
                await _progress(
                    f"⚠️ **FloodWait!** Telegram minta tunggu {e.seconds} detik.\n"
                    f"⏳ Auto-pause {wait_sec} detik... Jangan panic."
                )
                logger.warning(f"FloodWait: {e.seconds}s, pausing {wait_sec}s")
                await asyncio.sleep(wait_sec)
                await _progress("▶️ Melanjutkan setelah FloodWait...")
                failed += 1

            except PeerFloodError:
                stopped_reason = (
                    "🛑 PeerFloodError! Rate-limit berat. "
                    "Coba lagi dalam beberapa jam."
                )
                failed += 1
                logger.error("PeerFloodError — stopping")
                break

            except Exception as e:
                failed += 1
                logger.error(f"Unexpected error for {display}: {type(e).__name__}: {e}")

            # Delay acak anti-ban
            if idx < len(members) and not stopped_reason:
                delay = random.uniform(MIN_DELAY, MAX_DELAY)
                await asyncio.sleep(delay)

        elapsed = time.time() - start_time
        minutes = elapsed / 60

        return {
            "success": True,
            "added": added,
            "skipped": skipped,
            "failed": failed,
            "total_processed": added + skipped + failed,
            "total_members": len(members),
            "elapsed_minutes": round(minutes, 1),
            "stopped_reason": stopped_reason,
            "group_title": group_title,
            "error": None,
        }

    except Exception as e:
        return {"success": False, "error": f"Error: {type(e).__name__}: {e}"}
    finally:
        await client.disconnect()
