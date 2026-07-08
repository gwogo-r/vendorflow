"""Одноразовый логин Telethon для VendorFlow.

Запусти один раз: `python auth.py`, введи код, который придёт в Telegram на аккаунт
из TG_PHONE. Сессия сохранится в config/vendorflow.session, после чего main.py
подключается без вопросов. Повторно запускать не нужно, пока сессия жива.
"""
import asyncio
from pathlib import Path

from telethon import TelegramClient

from vendorflow.config import config


async def main():
    Path(config.tg_session).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(config.tg_session, config.tg_api_id, config.tg_api_hash)
    await client.start(phone=config.tg_phone or None)
    me = await client.get_me()
    print(f"\nАвторизован как: {me.first_name} (@{me.username})  id={me.id}")
    print("Сессия сохранена. Теперь запускай: python main.py")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
