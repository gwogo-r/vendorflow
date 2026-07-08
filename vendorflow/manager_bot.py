"""Бот менеджера: команды на запуск диалогов и уведомления о результатах.

Здесь Bot API уместен — менеджер сам пишет боту, поэтому ограничение «бот не пишет первым»
нас не касается. Живой контакт с подрядчиками идёт через Telethon (см. telegram_client).
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from .config import config
from .engine import Engine, Notifier
from .models import Contractor, Status, COL_STATUS

log = logging.getLogger("vendorflow.manager")


class TelegramNotifier(Notifier):
    """Шлёт менеджеру уведомления в его личный чат с ботом."""

    def __init__(self, bot: Bot, chat_id: int):
        self.bot = bot
        self.chat_id = chat_id

    async def notify(self, text: str) -> None:
        await self.bot.send_message(self.chat_id, text)


def build_dispatcher(engine: Engine) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(Command("contact"))
    async def cmd_contact(m: Message):
        # /contact @username Категория; краткое описание задачи
        args = (m.text or "").split(maxsplit=1)
        if len(args) < 2:
            await m.answer("Формат: /contact @username; краткое описание задачи")
            return
        rest = args[1]
        telegram, _, brief = rest.partition(";")
        c = Contractor(
            telegram=telegram.strip(),
            task_brief=brief.strip() or "задача уточняется",
            launch=True,  # команда = «отправлять», планировщик подхватит
        )
        added = engine.store.add_contractor_if_absent(c)
        if not added:
            await m.answer(f"{telegram.strip()} уже есть в базе — повторно не добавляю (дедуп).")
            return
        await m.answer(f"Ок, поставил {telegram.strip()} в очередь на первый контакт.")

    @dp.message(Command("status"))
    async def cmd_status(m: Message):
        rows = engine.store._all_rows()
        by_status: dict[str, int] = {}
        for r in rows:
            label = r.get(COL_STATUS, "?") or "?"
            by_status[label] = by_status.get(label, 0) + 1
        if not rows:
            await m.answer("База пустая.")
            return
        lines = [f"{k}: {v}" for k, v in by_status.items()]
        await m.answer("Статусы подрядчиков:\n" + "\n".join(lines))

    @dp.message(Command("stop"))
    async def cmd_stop(m: Message):
        # /stop @username — вручную выключить подрядчика
        args = (m.text or "").split(maxsplit=1)
        if len(args) < 2:
            await m.answer("Формат: /stop @username")
            return
        row, c = engine.store.get(args[1].strip())
        if c is None:
            await m.answer("Не нашёл такого подрядчика.")
            return
        c.status = Status.stopped
        engine.store.upsert(c)
        await m.answer(f"{args[1].strip()} выключен, автодиалог остановлен.")

    return dp


def make_bot() -> Bot:
    return Bot(config.manager_bot_token)
