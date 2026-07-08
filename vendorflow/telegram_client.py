"""Telethon-обёртка — отправка первого сообщения от обычного аккаунта.

Bot API не может писать первым тому, кто сам не начинал диалог с ботом, поэтому для
исходящих используется пользовательская MTProto-сессия. Печатаем "typing", чтобы выглядело
живо. Приём ответов вешается через on_message.
"""

from __future__ import annotations

import asyncio
import logging

from telethon import TelegramClient, events

from .config import config

log = logging.getLogger("vendorflow.telethon")


class TelethonSender:
    def __init__(self):
        self.client = TelegramClient(config.tg_session, config.tg_api_id, config.tg_api_hash)

    async def start(self):
        await self.client.start()
        log.info("Telethon-сессия запущена")

    async def send(self, telegram: str, text: str) -> None:
        entity = await self.client.get_entity(telegram)
        # короткая имитация набора текста перед отправкой
        async with self.client.action(entity, "typing"):
            await asyncio.sleep(min(len(text) / 20, 8))
        await self.client.send_message(entity, text)

    def on_message(self, handler):
        """handler(telegram: str, text: str, message_id: int) — вызывается на входящее в личке."""

        @self.client.on(events.NewMessage(incoming=True))
        async def _wrap(event):
            if not event.is_private:
                return
            sender = await event.get_sender()
            username = getattr(sender, "username", None) or str(event.chat_id)
            await handler(username, event.raw_text, event.id)

    async def run_forever(self):
        await self.client.run_until_disconnected()
