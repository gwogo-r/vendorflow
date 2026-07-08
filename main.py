"""Точка входа live-режима: связывает Telethon (исходящие), бот менеджера и оркестратор.

Запуск: python main.py
Пока DRY_RUN=true подрядчикам ничего реально не уходит — сообщения только в логах.
"""

from __future__ import annotations

import asyncio
import logging

from vendorflow.config import config
from vendorflow.engine import Engine, DryRunSender
from vendorflow.llm_pipeline import LLMPipeline
from vendorflow.manager_bot import TelegramNotifier, build_dispatcher, make_bot
from vendorflow.state_store import StateStore
from vendorflow.telegram_client import TelethonSender

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vendorflow.main")


async def poll_ready_loop(engine: Engine):
    """Периодически берём подрядчиков в очереди и пишем им первыми — с учётом времени и лимитов."""
    while True:
        try:
            await engine.contact_next_ready()
        except Exception:
            log.exception("ошибка в цикле первых контактов")
        await asyncio.sleep(60)


async def main():
    store = StateStore()
    llm = LLMPipeline()

    bot = make_bot()
    notifier = TelegramNotifier(bot, config.manager_chat_id)

    # исходящие подрядчикам: живой Telethon или заглушка в dry-run
    if config.dry_run:
        sender = DryRunSender()
        log.info("DRY-RUN включён — подрядчикам ничего не отправляется")
    else:
        telethon = TelethonSender()
        await telethon.start()
        sender = telethon

    engine = Engine(store, llm, sender=sender, notifier=notifier)

    # входящие ответы подрядчиков → в оркестратор
    if not config.dry_run:
        telethon.on_message(engine.handle_incoming)

    dp = build_dispatcher(engine)

    tasks = [poll_ready_loop(engine), dp.start_polling(bot)]
    if not config.dry_run:
        tasks.append(telethon.run_forever())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
