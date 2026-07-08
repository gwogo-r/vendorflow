"""Детерминированный планировщик: рабочие часы, паузы, дневные лимиты, safety-флаги.

Это НЕ задача LLM. Модель не имеет надёжных часов и состояния между вызовами, поэтому
решение «можно ли и когда отправлять» принимается здесь, обычным кодом.
"""

from __future__ import annotations

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import config
from .models import Contractor, now_iso


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.timezone))


def is_working_time(dt: datetime | None = None) -> bool:
    """Пн-Пт, 10:00-18:00 по часовому поясу из конфига."""
    dt = dt or _now()
    if dt.weekday() >= 5:  # 5,6 — суббота, воскресенье
        return False
    return config.work_hours_start <= dt.hour < config.work_hours_end


def sending_blocked() -> tuple[bool, str]:
    """Глобальные предохранители. Возвращает (заблокировано, причина)."""
    if config.kill_switch:
        return True, "kill switch включён"
    if config.test_run:
        return False, ""  # тестовый прогон игнорирует рабочие часы
    if not is_working_time():
        return True, "нерабочее время (Пн-Пт 10:00-18:00)"
    return False, ""


def daily_new_contact_limit_reached(contacted_today: int) -> bool:
    if config.test_run:
        return False
    return contacted_today >= config.max_new_contacts_per_day


def contractor_daily_limit_reached(c: Contractor) -> bool:
    """Лимит сообщений одному подрядчику в день. Счётчик привязан к дате."""
    if config.test_run:
        return False
    today = now_iso()[:10]
    if c.messages_sent_date != today:
        return False
    return c.messages_sent_today >= config.max_messages_per_contact_per_day


def register_sent(c: Contractor) -> None:
    """Отметить факт отправки: счётчик за день + таймстемпы."""
    today = now_iso()[:10]
    if c.messages_sent_date != today:
        c.messages_sent_date = today
        c.messages_sent_today = 0
    c.messages_sent_today += 1
    c.last_outbound_at = now_iso()


def pause_before_first() -> int:
    if config.test_run:
        return random.randint(2, 4)  # в тесте не ждём минуты, но паузу оставляем «живой»
    lo, hi = config.pause_before_first
    return random.randint(lo, hi)


def pause_before_reply() -> int:
    if config.test_run:
        return random.randint(2, 4)
    lo, hi = config.pause_before_reply
    return random.randint(lo, hi)
