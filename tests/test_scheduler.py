from datetime import datetime
from zoneinfo import ZoneInfo

from vendorflow import scheduler
from vendorflow.config import config
from vendorflow.models import Contractor


def _dt(y, m, d, h):
    return datetime(y, m, d, h, tzinfo=ZoneInfo(config.timezone))


def test_working_time_weekday_in_hours():
    # среда 12:00
    assert scheduler.is_working_time(_dt(2026, 7, 8, 12))


def test_not_working_night():
    assert not scheduler.is_working_time(_dt(2026, 7, 8, 3))


def test_not_working_weekend():
    # суббота
    assert not scheduler.is_working_time(_dt(2026, 7, 11, 12))


def test_contractor_daily_limit():
    from vendorflow.models import now_iso
    c = Contractor(telegram="@x")
    c.messages_sent_date = now_iso()[:10]
    c.messages_sent_today = config.max_messages_per_contact_per_day
    assert scheduler.contractor_daily_limit_reached(c)


def test_register_sent_resets_on_new_day():
    c = Contractor(telegram="@x")
    c.messages_sent_date = "2000-01-01"
    c.messages_sent_today = 5
    scheduler.register_sent(c)
    assert c.messages_sent_today == 1  # счётчик сбросился на новый день


def test_test_run_bypasses_gating_but_not_kill_switch():
    # среди ночи sending_blocked обычно True — тестовый прогон должен снять этот блок
    object.__setattr__(config, "test_run", True)
    try:
        assert scheduler.sending_blocked() == (False, "")
        assert not scheduler.daily_new_contact_limit_reached(10_000)
        # но аварийный стоп должен срабатывать даже в тесте
        object.__setattr__(config, "kill_switch", True)
        assert scheduler.sending_blocked()[0]
    finally:
        object.__setattr__(config, "kill_switch", False)
        object.__setattr__(config, "test_run", False)
