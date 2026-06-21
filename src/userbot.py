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
import re
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
    DATA_DIR,
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


async def check_session(phone: Optional[str] = None) -> dict:
    """
    Mengecek apakah session tertentu (atau session pertama jika None) masih valid.

    Returns:
        dict: {"authorized": bool, "user": User|None, "phone": str|None, "error": str|None}
    """
    if not phone:
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
    phone: str,
    source_group_input: str,
    progress_callback: Optional[Callable] = None,
    csv_filename: str = "members.csv",
) -> dict:
    """
    Scrape member dari grup sumber dan simpan ke CSV.

    Args:
        phone: Nomor telepon sesi yang digunakan.
        source_group_input: Username/link/ID grup sumber.
        progress_callback: Async callback(message) untuk update progress.

    Returns:
        dict dengan hasil scraping.
    """
    if not phone:
        return {"success": False, "error": "Nomor telepon tidak ditentukan."}

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
        csv_path = DATA_DIR / csv_filename
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
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


async def scrape_contacts(
    phone: str,
    progress_callback: Optional[Callable] = None,
    csv_filename: str = "members.csv",
) -> dict:
    """
    Scrape member dari daftar kontak akun dan simpan ke CSV.

    Args:
        phone: Nomor telepon sesi yang digunakan.
        progress_callback: Async callback(message) untuk update progress.

    Returns:
        dict dengan hasil scraping.
    """
    if not phone:
        return {"success": False, "error": "Nomor telepon tidak ditentukan."}

    client = get_client(phone)

    async def _progress(msg):
        if progress_callback:
            await progress_callback(msg)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "error": "Session expired! Login ulang."}

        await _progress("🔍 Mengambil daftar kontak dari akun...")

        from telethon.tl.functions.contacts import GetContactsRequest

        # Ambil kontak
        contacts_result = await client(GetContactsRequest(hash=0))
        users = getattr(contacts_result, "users", [])

        if not users:
            return {"success": False, "error": "Tidak ada kontak yang ditemukan atau gagal mengambil kontak."}

        await _progress(f"✅ Ditemukan {len(users)} kontak.\n⏳ Menyaring dan menyimpan...")

        filtered = []
        skipped_bots = 0
        skipped_deleted = 0

        for user in users:
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
                "error": "Tidak ada kontak valid yang bisa disimpan.",
            }

        # Save CSV
        csv_path = DATA_DIR / csv_filename
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["user_id", "access_hash", "username", "first_name", "last_name"],
            )
            writer.writeheader()
            writer.writerows(filtered)

        logger.info(f"Scraped {len(filtered)} contacts")

        return {
            "success": True,
            "total": len(users),
            "saved": len(filtered),
            "skipped_bots": skipped_bots,
            "skipped_deleted": skipped_deleted,
            "error": None,
        }

    except Exception as e:
        return {"success": False, "error": f"Error: {type(e).__name__}: {e}"}
    finally:
        await client.disconnect()


async def get_contacts_list(phone: str) -> dict:
    """
    Mengambil daftar kontak yang valid langsung ke memory (tanpa menulis ke CSV).

    Returns:
        dict: {"success": bool, "contacts": list[dict], "error": str|None}
    """
    if not phone:
        return {"success": False, "contacts": [], "error": "Nomor telepon tidak ditentukan."}

    client = get_client(phone)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "contacts": [], "error": "Session expired! Login ulang."}

        from telethon.tl.functions.contacts import GetContactsRequest

        # Ambil kontak
        contacts_result = await client(GetContactsRequest(hash=0))
        users = getattr(contacts_result, "users", [])

        filtered = []
        for user in users:
            if user.bot or user.deleted:
                continue

            filtered.append({
                "user_id": user.id,
                "access_hash": user.access_hash,
                "username": user.username or "",
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
            })

        return {"success": True, "contacts": filtered, "error": None}

    except Exception as e:
        return {"success": False, "contacts": [], "error": f"Error: {type(e).__name__}: {e}"}
    finally:
        await client.disconnect()




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ADD MEMBER OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def load_members(csv_filename: str = "members.csv") -> list[dict]:
    """Membaca data member dari CSV. Mengembalikan list kosong jika file tidak ada."""
    csv_path = DATA_DIR / csv_filename
    if not csv_path.exists():
        return []
    members = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            members.append(row)
    return members


async def _resolve_and_join_group(client, group_input: str):
    """
    Helper internal untuk me-resolve grup/channel dan otomatis bergabung (join) jika belum.
    Mengembalikan entity grup yang valid.
    """
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest, CheckChatInviteRequest
    from telethon.tl.types import ChatInviteAlready, Channel, Chat
    from telethon.errors import UserAlreadyParticipantError

    group_input = group_input.strip()
    entity = None

    # 1. Coba deteksi link private
    private_match = re.search(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)([a-zA-Z0-9_\-]+)", group_input)
    if private_match:
        invite_hash = private_match.group(1)
        try:
            invite_info = await client(CheckChatInviteRequest(invite_hash))
            if isinstance(invite_info, ChatInviteAlready):
                entity = invite_info.chat
            else:
                # Belum bergabung, coba join
                updates = await client(ImportChatInviteRequest(invite_hash))
                if hasattr(updates, "chats") and updates.chats:
                    entity = updates.chats[0]
        except UserAlreadyParticipantError:
            # Jika sudah join tapi CheckChatInviteRequest tidak mengembalikan entity
            pass
        except Exception as e:
            logger.warning(f"Gagal bergabung ke grup private via hash {invite_hash}: {e}")
            
    # 2. Jika bukan link private atau langkah di atas belum mendapatkan entity
    if not entity:
        # Bersihkan link publik jika ada
        pub_match = re.search(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{5,})", group_input)
        entity_identifier = pub_match.group(1) if pub_match else group_input

        if isinstance(entity_identifier, str) and entity_identifier.startswith("@"):
            entity_identifier = entity_identifier[1:]

        try:
            entity = await client.get_entity(entity_identifier)
            # Jika supergrup/channel publik, join jika belum join
            if isinstance(entity, Channel):
                try:
                    await client(JoinChannelRequest(entity))
                except Exception as join_err:
                    logger.warning(f"Gagal bergabung ke channel/supergrup publik: {join_err}")
        except Exception as e:
            # Jika gagal get_entity, coba join langsung menggunakan username/identifier
            if isinstance(entity_identifier, str) and not entity_identifier.startswith("-") and not entity_identifier.isdigit():
                try:
                    updates = await client(JoinChannelRequest(entity_identifier))
                    if hasattr(updates, "chats") and updates.chats:
                        entity = updates.chats[0]
                except Exception as join_err:
                    logger.warning(f"Gagal bergabung via username/identifier {entity_identifier}: {join_err}")

    # 3. Fallback terakhir jika entity masih None
    if not entity:
        # Bersihkan prefix t.me/ jika ada untuk pencarian get_entity
        clean_input = group_input
        pub_match = re.search(r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{5,})", group_input)
        if pub_match:
            clean_input = pub_match.group(1)
        if isinstance(clean_input, str) and clean_input.startswith("@"):
            clean_input = clean_input[1:]

        try:
            entity = await client.get_entity(clean_input)
        except Exception:
            # Cari dari dialog user
            async for dialog in client.iter_dialogs():
                if dialog.is_group or dialog.is_channel:
                    if dialog.name == group_input:
                        entity = dialog.entity
                        break
            if not entity:
                raise ValueError(f"Tidak dapat menemukan atau mengakses grup '{group_input}'. Pastikan link/username benar.")

    return entity


async def resolve_group(phone: str, group_input: str) -> dict:
    """
    Resolve nama grup target dan kembalikan info.
    Jika user belum masuk ke grup/channel tersebut, bot akan otomatis bergabung (join) terlebih dahulu.

    Returns:
        dict: {"success": bool, "title": str, "error": str|None}
    """
    if not phone:
        return {"success": False, "title": "", "error": "Nomor telepon tidak ditentukan."}

    client = get_client(phone)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "title": "", "error": "Session expired!"}

        entity = await _resolve_and_join_group(client, group_input)
        title = getattr(entity, "title", group_input)
        return {"success": True, "title": title, "error": None}
    except (ValueError, Exception) as e:
        return {"success": False, "title": "", "error": str(e)}
    finally:
        await client.disconnect()


async def add_members(
    phone: str,
    target_group_input: str,
    members: list[dict],
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Menambahkan member ke grup target dengan rate limiting dan error handling.

    Args:
        phone: Nomor telepon sesi yang digunakan.
        target_group_input: Username/link/ID grup target.
        members: List of dict dari CSV.
        progress_callback: Async callback(message) untuk update progress.

    Returns:
        dict hasil akhir dengan statistik.
    """
    if not phone:
        return {"success": False, "error": "Nomor telepon tidak ditentukan."}

    client = get_client(phone)

    async def _progress(msg):
        if progress_callback:
            await progress_callback(msg)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "error": "Session expired! Login ulang."}

        # Resolve target group and auto-join if not joined
        try:
            target_group = await _resolve_and_join_group(client, target_group_input)
        except Exception as e:
            return {"success": False, "error": f"Grup target tidak ditemukan atau gagal bergabung: {e}"}

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
                # Resolve the entity first to refresh Telethon's internal cache
                # and announce interaction to Telegram, increasing invitation success rate.
                try:
                    await client.get_entity(int(uid))
                except Exception as ent_err:
                    logger.debug(f"[{phone}] Failed to get entity for {display} before invite: {ent_err}")

                user_peer = InputPeerUser(user_id=int(uid), access_hash=int(ahash))
                await client(InviteToChannelRequest(target_group, [user_peer]))
                added += 1
                logger.info(f"[{phone}] Added: {display}")

                # Update progress setiap 5 member atau yang pertama
                if added == 1 or added % 5 == 0:
                    await _progress(
                        f"📊 Progress: {idx}/{len(members)}\n"
                        f"✅ Ditambahkan: {added} | ⏩ Skip: {skipped} | ❌ Gagal: {failed}"
                    )

            except UserAlreadyParticipantError:
                skipped += 1
                logger.info(f"[{phone}] Already member: {display}")

            except UserPrivacyRestrictedError:
                skipped += 1
                logger.info(f"[{phone}] Privacy restricted: {display}")

            except UserNotMutualContactError:
                skipped += 1
                logger.info(f"[{phone}] Not mutual contact: {display}")

            except UserChannelsTooMuchError:
                skipped += 1
                logger.info(f"[{phone}] Too many channels: {display}")

            except UserKickedError:
                skipped += 1
                logger.info(f"[{phone}] User was kicked: {display}")

            except UserBannedInChannelError:
                skipped += 1
                logger.info(f"[{phone}] User banned: {display}")

            except InputUserDeactivatedError:
                skipped += 1
                logger.info(f"[{phone}] Deactivated account: {display}")

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
                logger.warning(f"[{phone}] FloodWait: {e.seconds}s, pausing {wait_sec}s")
                await asyncio.sleep(wait_sec)
                await _progress("▶️ Melanjutkan setelah FloodWait...")
                failed += 1

            except PeerFloodError:
                stopped_reason = (
                    "🛑 PeerFloodError! Rate-limit berat. "
                    "Coba lagi dalam beberapa jam."
                )
                failed += 1
                logger.error(f"[{phone}] PeerFloodError — stopping")
                break

            except Exception as e:
                failed += 1
                logger.error(f"[{phone}] Unexpected error for {display}: {type(e).__name__}: {e}")

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


def generate_phone_numbers(base_number: str, count: int) -> list[str]:
    """
    Men-generate daftar nomor telepon berurutan (sekuensial) dimulai dari base_number.
    """
    has_plus = base_number.startswith("+")
    digits_only = "".join(c for c in base_number if c.isdigit())
    if not digits_only:
        return []

    length = len(digits_only)
    base_int = int(digits_only)

    numbers = []
    for i in range(count):
        current_int = base_int + i
        current_str = f"{current_int:0{length}d}"
        if has_plus:
            numbers.append("+" + current_str)
        else:
            numbers.append(current_str)

    return numbers


async def validate_phone_numbers(
    phone: str,
    numbers_list: list[str],
    prefix_name: str,
    progress_callback: Optional[Callable] = None,
    csv_filename: str = "members.csv",
) -> dict:
    """
    Validasi daftar nomor telepon di Telegram menggunakan API ImportContacts.
    Nomor yang valid akan disimpan ke members.csv dan disimpan sebagai kontak di akun Telegram.
    """
    if not phone:
        return {"success": False, "error": "Nomor telepon tidak ditentukan."}

    client = get_client(phone)

    async def _progress(msg):
        if progress_callback:
            await progress_callback(msg)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            return {"success": False, "error": "Session expired! Login ulang."}

        await _progress(f"🔍 Mulai memvalidasi {len(numbers_list)} nomor di Telegram...")

        from telethon.tl.functions.contacts import ImportContactsRequest, GetContactsRequest
        from telethon.tl.types import InputPhoneContact

        # Ambil kontak yang sudah ada untuk mengenali nomor yang sudah terdaftar sebelumnya
        try:
            existing_contacts = await client(GetContactsRequest(hash=0))
            existing_users = getattr(existing_contacts, "users", [])
        except Exception as e:
            logger.error(f"Error fetching existing contacts: {e}")
            existing_users = []

        existing_phones = {}
        for u in existing_users:
            if u.phone:
                norm = "".join(c for c in u.phone if c.isdigit())
                existing_phones[norm] = u

        # Buat pemetaan nomor telepon (digit saja) ke indeks urutannya (1-based)
        phone_to_index = {}
        for idx, num in enumerate(numbers_list):
            norm = "".join(c for c in num if c.isdigit())
            phone_to_index[norm] = idx + 1

        valid_users = []
        batch_size = 1
        total_checked = 0
        i = 0

        while i < len(numbers_list):
            batch = numbers_list[i:i+batch_size]
            contacts = []
            cid_to_info = {}

            for idx_in_batch, num in enumerate(batch):
                cid = random.randint(1000000, 9999999)
                global_idx = i + idx_in_batch + 1
                # Simpan kontak dengan nama prefix_name(indeks)
                first_name = f"{prefix_name}({global_idx})"
                contacts.append(InputPhoneContact(client_id=cid, phone=num, first_name=first_name, last_name=""))
                cid_to_info[cid] = {"phone": num, "idx": global_idx}

            try:
                import_res = await client(ImportContactsRequest(contacts))
                imported_users = getattr(import_res, "users", [])
                imported_list = getattr(import_res, "imported", [])

                # Map user_id to our generated info via client_id
                user_id_to_info = {}
                for imp in imported_list:
                    info = cid_to_info.get(imp.client_id)
                    if info:
                        user_id_to_info[imp.user_id] = info

                for user in imported_users:
                    if user.bot or user.deleted:
                        continue

                    # Try to map using client_id first, then fallback
                    info = user_id_to_info.get(user.id)
                    if info:
                        v_name = f"{prefix_name}({info['idx']})"
                    else:
                        norm_phone = "".join(c for c in (user.phone or "") if c.isdigit())
                        idx = phone_to_index.get(norm_phone)
                        if idx is not None:
                            v_name = f"{prefix_name}({idx})"
                        else:
                            v_name = f"{prefix_name}({user.phone or batch[0]})"
                    
                    if not any(v["user_id"] == user.id for v in valid_users):
                        valid_users.append({
                            "user_id": user.id,
                            "access_hash": user.access_hash,
                            "username": user.username or "",
                            "first_name": v_name,
                            "last_name": user.last_name or "",
                        })

                # Cek jika ada nomor di batch yang sebenarnya sudah ada di kontak
                for num in batch:
                    norm_num = "".join(c for c in num if c.isdigit())
                    if norm_num in existing_phones:
                        existing_u = existing_phones[norm_num]
                        if not any(v["user_id"] == existing_u.id for v in valid_users):
                            idx = phone_to_index.get(norm_num)
                            v_name = f"{prefix_name}({idx})" if idx else f"{prefix_name}({num})"
                            valid_users.append({
                                "user_id": existing_u.id,
                                "access_hash": existing_u.access_hash,
                                "username": existing_u.username or "",
                                "first_name": v_name,
                                "last_name": existing_u.last_name or "",
                            })

                # CATATAN: Kita TIDAK memanggil DeleteContactsRequest di sini
                # agar kontak-kontak yang valid ini tetap tersimpan di akun Telegram Anda.

                # Move to next batch
                total_checked += len(batch)
                i += batch_size

            except FloodWaitError as e:
                wait_sec = e.seconds + FLOOD_WAIT_BUFFER
                await _progress(
                    f"⚠️ **FloodWait Validator!** Telegram minta tunggu {e.seconds} detik.\n"
                    f"⏳ Auto-pause {wait_sec} detik... Jangan panik."
                )
                logger.warning(f"[{phone}] FloodWait in Validator: {e.seconds}s, pausing {wait_sec}s")
                await asyncio.sleep(wait_sec)
                # Do NOT increment i, so it retries the same batch.

            except PeerFloodError:
                await _progress(
                    "🛑 **PeerFloodError!** Akun terindikasi spam berat saat import kontak.\n"
                    "Proses validasi dihentikan."
                )
                logger.error(f"[{phone}] PeerFloodError in Validator — stopping")
                break

            except Exception as batch_err:
                await _progress(f"⚠️ Error pada batch check: {type(batch_err).__name__}: {batch_err}")
                logger.error(f"Error pada batch {i}: {batch_err}")
                # Move to next batch to prevent infinite loop on other unexpected errors
                total_checked += len(batch)
                i += batch_size

            if total_checked % 10 == 0 or i >= len(numbers_list):
                await _progress(
                    f"📊 Progres Validasi: {total_checked}/{len(numbers_list)} nomor\n"
                    f"✅ Aktif Telegram: **{len(valid_users)}**"
                )

            await asyncio.sleep(random.uniform(1.5, 3.0))

        if not valid_users:
            return {
                "success": True,
                "total_checked": total_checked,
                "valid_count": 0,
                "error": "Tidak ada nomor yang terdaftar di Telegram dari hasil generator."
            }

        # Simpan ke CSV agar bisa langsung dipakai di menu Add Member
        csv_path = DATA_DIR / csv_filename
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["user_id", "access_hash", "username", "first_name", "last_name"],
            )
            writer.writeheader()
            for u in valid_users:
                writer.writerow({
                    "user_id": u["user_id"],
                    "access_hash": u["access_hash"],
                    "username": u["username"],
                    "first_name": u["first_name"],
                    "last_name": u["last_name"],
                })

        logger.info(f"Validated {len(valid_users)} active Telegram accounts out of {total_checked} generated numbers")

        return {
            "success": True,
            "total_checked": total_checked,
            "valid_count": len(valid_users),
            "error": None
        }

    except Exception as e:
        return {"success": False, "error": f"Error: {type(e).__name__}: {e}"}
    finally:
        await client.disconnect()
