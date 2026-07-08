"""Оркестратор: связывает состояние, LLM, планировщик и отправку.

Здесь принимаются все решения о переходах статусов. Отправка вынесена за интерфейс Sender,
чтобы dry-run и живой Telethon подключались одинаково.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from .config import config
from .llm_pipeline import LLMPipeline
from .models import Contractor, Status
from .state_store import StateStore
from . import scheduler

log = logging.getLogger("vendorflow")


class Sender(Protocol):
    async def send(self, telegram: str, text: str) -> None: ...


class Notifier(Protocol):
    async def notify(self, text: str) -> None: ...


class DryRunSender:
    """Ничего не отправляет — только пишет в лог. Включён, пока DRY_RUN=true."""

    async def send(self, telegram: str, text: str) -> None:
        log.info("[DRY-RUN] -> %s: %s", telegram, text)


class LogNotifier:
    async def notify(self, text: str) -> None:
        log.info("[MANAGER] %s", text)


class Engine:
    def __init__(
        self,
        store: StateStore,
        llm: LLMPipeline,
        sender: Sender | None = None,
        notifier: Notifier | None = None,
    ):
        self.store = store
        self.llm = llm
        self.sender = sender or DryRunSender()
        self.notifier = notifier or LogNotifier()

    async def _deliver(self, c: Contractor, text: str) -> bool:
        """Единая точка отправки: проверяет предохранители и лимиты, потом шлёт (или dry-run)."""
        blocked, why = scheduler.sending_blocked()
        if blocked:
            log.info("отправка отложена (%s): %s", why, c.telegram_key)
            return False
        if scheduler.contractor_daily_limit_reached(c):
            log.info("дневной лимит на подрядчика исчерпан: %s", c.telegram_key)
            return False

        await self.sender.send(c.telegram, text)
        c.add_message("assistant", text)
        scheduler.register_sent(c)
        return True

    # первое сообщение

    async def contact_next_ready(self) -> Contractor | None:
        """Взять одного подрядчика в статусе ready_to_contact и написать ему первым."""
        blocked, why = scheduler.sending_blocked()
        if blocked:
            log.info("новые контакты сейчас недоступны: %s", why)
            return None
        if scheduler.daily_new_contact_limit_reached(self.store.count_contacted_today()):
            log.info("дневной лимит новых подрядчиков исчерпан")
            return None

        batch = self.store.list_launch_pending()
        if not batch:
            return None
        _, c = batch[0]

        # идемпотентность: если по какой-то причине уже писали — не дублируем
        if c.first_message_sent_at:
            c.status = Status.waiting_reply
            self.store.upsert(c)
            return None

        text = self.llm.compose(c, next_missing_field="price")
        if not text:
            return None

        await asyncio.sleep(scheduler.pause_before_first())
        if await self._deliver(c, text):
            c.first_message_sent_at = c.last_outbound_at
            c.status = Status.waiting_reply
            self.store.upsert(c)
            log.info("первое сообщение отправлено: %s", c.telegram_key)
            return c
        return None

    # входящий ответ

    async def handle_incoming(self, telegram: str, text: str, message_id: int = 0) -> Contractor | None:
        row_num, c = self.store.get(telegram)
        if c is None:
            log.info("входящее от неизвестного подрядчика, пропускаем: %s", telegram)
            return None

        # дедуп входящих: тот же message_id не обрабатываем повторно
        if message_id and message_id <= c.last_inbound_message_id:
            log.info("повторный message_id, пропускаем: %s", telegram)
            return c
        if message_id:
            c.last_inbound_message_id = message_id

        c.add_message("contractor", text)
        from .models import now_iso
        c.last_inbound_at = now_iso()

        analysis = self.llm.analyze(c)
        self._apply_extracted(c, analysis.extracted)

        if analysis.stop:
            return await self._escalate(c, analysis.stop_reason or analysis.reason, analysis.manager_summary)

        if analysis.completed:
            c.status = Status.completed
            c.manager_summary = analysis.manager_summary
            row = self.store.upsert(c)
            await self.notifier.notify(
                f"✅ Собраны вводные по {c.name or c.telegram_key}\n"
                f"👤 Чат: {c.telegram_url}\n"
                f"📄 Таблица (строка {row}): {config.sheet_url(row)}\n\n"
                f"{analysis.manager_summary}"
            )
            return c

        # можно продолжать — один уточняющий вопрос
        await asyncio.sleep(scheduler.pause_before_reply())
        text_out = self.llm.compose(c, analysis.next_missing_field)
        if not text_out:
            # LLM повторился или пусто — не крутим цикл, отдаём человеку
            return await self._escalate(c, "не удалось сформулировать новый вопрос", analysis.manager_summary)

        await self._deliver(c, text_out)
        c.status = Status.waiting_reply
        self.store.upsert(c)
        return c

    async def _escalate(self, c: Contractor, reason: str, summary: str) -> Contractor:
        """Стоп-правило сработало: ничего подрядчику не шлём, зовём менеджера."""
        c.status = Status.needs_human_review
        c.review_reason = reason
        c.manager_summary = summary
        row = self.store.upsert(c)
        await self.notifier.notify(
            f"⛔ Нужна ручная проверка: {c.name or c.telegram_key}\n"
            f"👤 Чат: {c.telegram_url}\n"
            f"📄 Таблица (строка {row}): {config.sheet_url(row)}\n\n"
            f"Причина: {reason}\n{summary}"
        )
        log.info("эскалация менеджеру: %s (%s)", c.telegram_key, reason)
        return c

    @staticmethod
    def _apply_extracted(c: Contractor, extracted: dict) -> None:
        """Пишем поле, только если пришло непустое значение — не затираем собранное ответом 'не знаю'."""
        for field in ("price", "deadline", "conditions", "prepayment", "availability"):
            val = extracted.get(field)
            if val:
                setattr(c, field, val)
        for lst in ("contractor_questions", "requested_materials", "risk_flags"):
            val = extracted.get(lst)
            if val:
                setattr(c, lst, val)
        if "missing_fields" in extracted:
            c.missing_fields = extracted["missing_fields"]
        if extracted.get("confidence") is not None:
            c.confidence = float(extracted["confidence"])
