import asyncio

from vendorflow.engine import Engine
from vendorflow.llm_pipeline import Analysis
from vendorflow.models import Contractor, Status


class FakeStore:
    """Хранилище в памяти — по ключу telegram, как настоящее, но без Google."""

    def __init__(self, contractors=None):
        self.rows = {c.telegram_key: c for c in (contractors or [])}

    def get(self, telegram):
        from vendorflow.normalize import normalize_telegram
        c = self.rows.get(normalize_telegram(telegram))
        return (1 if c else None), c

    def upsert(self, c):
        self.rows[c.telegram_key] = c
        return 1


class FakeLLM:
    def __init__(self, analysis, reply="уточните, пожалуйста, срок"):
        self._analysis = analysis
        self._reply = reply

    def analyze(self, c):
        return self._analysis

    def compose(self, c, next_missing_field):
        return self._reply


class RecordingSender:
    def __init__(self):
        self.sent = []

    async def send(self, telegram, text):
        self.sent.append((telegram, text))


class RecordingNotifier:
    def __init__(self):
        self.msgs = []

    async def notify(self, text):
        self.msgs.append(text)


def _stop_analysis(reason="подрядчик просит созвон"):
    return Analysis(stop=True, completed=False, stop_reason=reason,
                    next_missing_field=None, extracted={}, manager_summary="сводка", reason=reason)


def _completed_analysis():
    return Analysis(stop=False, completed=True, stop_reason=None, next_missing_field=None,
                    extracted={"price": "50000", "deadline": "3 дня", "conditions": "по договорённости"},
                    manager_summary="цена/сроки/условия собраны", reason="всё собрано")


def test_stop_rule_escalates_and_does_not_send():
    c = Contractor(telegram="@vendor", name="Вендор")
    store = FakeStore([c])
    sender = RecordingSender()
    notifier = RecordingNotifier()
    engine = Engine(store, FakeLLM(_stop_analysis()), sender=sender, notifier=notifier)

    asyncio.run(engine.handle_incoming("@vendor", "давайте созвонимся", message_id=1))

    assert store.rows["vendor"].status == Status.needs_human_review
    assert sender.sent == []            # подрядчику ничего не ушло
    assert len(notifier.msgs) == 1      # менеджера позвали


def test_completed_marks_done():
    c = Contractor(telegram="@vendor")
    store = FakeStore([c])
    engine = Engine(store, FakeLLM(_completed_analysis()),
                    sender=RecordingSender(), notifier=RecordingNotifier())

    asyncio.run(engine.handle_incoming("@vendor", "50000, 3 дня, работаю по договорённости", message_id=1))

    assert store.rows["vendor"].status == Status.completed


def test_duplicate_incoming_ignored():
    c = Contractor(telegram="@vendor")
    c.last_inbound_message_id = 5
    store = FakeStore([c])
    engine = Engine(store, FakeLLM(_stop_analysis()),
                    sender=RecordingSender(), notifier=RecordingNotifier())

    # message_id меньше уже виденного — не обрабатываем
    asyncio.run(engine.handle_incoming("@vendor", "повтор", message_id=3))
    assert store.rows["vendor"].status == Status.ready_to_contact  # статус не менялся
