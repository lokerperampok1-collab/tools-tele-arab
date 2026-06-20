"""
main.py — Launcher
====================
Entry point utama. Menjalankan bot Telegram.

Cara pakai:
    python main.py
"""

from bot import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
