"""Оффлайн-демо VendorFlow — БЕЗ Telegram, Google и API-ключей.

Движок (engine, стоп-правила, извлечение данных, статусы, эскалация) — настоящий.
Заглушены только внешние сервисы: Telegram → печать в консоль, Google Sheets → память,
LLM → сценарный мок (в бою здесь реальный vendorflow.llm_pipeline).

Запуск:  python demo.py
"""
import asyncio

from vendorflow import scheduler
from vendorflow.engine import Engine
from vendorflow.llm_pipeline import Analysis
from vendorflow.models import Contractor, Status, STATUS_LABELS
from vendorflow.normalize import normalize_telegram

# в демо не ждём рабочих часов и пауз — прогон должен быть мгновенным
scheduler.pause_before_first = lambda: 0
scheduler.pause_before_reply = lambda: 0
scheduler.sending_blocked = lambda: (False, "")
scheduler.daily_new_contact_limit_reached = lambda n: False
scheduler.contractor_daily_limit_reached = lambda c: False


class InMemoryStore:
    """Google Sheets в памяти — тот же интерфейс, что у настоящего StateStore."""

    def __init__(self):
        self.rows: dict[str, Contractor] = {}

    def get(self, tg):
        c = self.rows.get(normalize_telegram(tg))
        return (1 if c else None), c

    def upsert(self, c):
        self.rows[c.telegram_key] = c
        return list(self.rows).index(c.telegram_key) + 2

    def add_contractor_if_absent(self, c):
        if c.telegram_key in self.rows:
            return False
        self.rows[c.telegram_key] = c
        return True

    def list_launch_pending(self):
        return [(0, c) for c in self.rows.values()
                if c.launch and not c.first_message_sent_at
                and c.status not in (Status.stopped, Status.completed)]

    def count_contacted_today(self):
        return 0


class PrintSender:
    async def send(self, tg, text):
        print(f"   💬 агент → {tg}:\n      {text}\n")


class PrintNotifier:
    async def notify(self, text):
        print("   🔔 УВЕДОМЛЕНИЕ МЕНЕДЖЕРУ:\n      " + text.replace("\n", "\n      ") + "\n")


class MockLLM:
    """Вместо OpenAI/claude — сценарные ответы, чтобы демо шло без ключей и детерминированно.
    В боевом режиме этот класс заменяется на vendorflow.llm_pipeline.LLMPipeline."""

    def compose(self, c, next_missing_field):
        wrote_before = any(m["from"] == "assistant" for m in c.history)
        if not wrote_before:
            return (f"Добрый день! Есть задача: {c.task_brief}. "
                    f"Хотим понять, сможете ли взять. Сориентируете по стоимости?")
        return "Спасибо. Подскажите, пожалуйста, по срокам и условиям работы?"

    def analyze(self, c):
        last = c.history[-1]["text"].lower() if c.history else ""
        if "созвон" in last or "позвон" in last:
            return Analysis(
                stop=True, completed=False,
                stop_reason="просит созвон — голосовое решение остаётся за менеджером",
                next_missing_field=None, extracted={},
                manager_summary=f"{c.telegram_key}: просит созвониться, автоматика остановлена.",
                reason="стоп-правило: запрос созвона",
            )
        if ("сто" in last or "100" in last) and "рубл" in last:  # смысловая аномалия в цене
            return Analysis(
                stop=True, completed=False, stop_reason="цена выглядит нереалистично (~100 ₽)",
                next_missing_field=None, extracted={"price": "100 ₽"},
                manager_summary=f"{c.telegram_key}: назвал ~100 ₽ — вероятно ошибка/непонимание объёма.",
                reason="стоп-правило: аномальная цена",
            )
        return Analysis(
            stop=False, completed=True, stop_reason=None, next_missing_field=None,
            extracted={"price": "5000 ₽", "deadline": "неделя", "conditions": "предоплата 50%"},
            manager_summary=f"{c.telegram_key}: 5000 ₽, неделя, предоплата 50% — вводные собраны.",
            reason="все поля собраны",
        )


SCENARIO = [
    ("@montazh_pro", "смонтировать рекламный ролик ~60с", "5000, неделя, работаю по предоплате 50%"),
    ("@budget_king", "нарезка длинного видео на shorts", "сто рублей"),
    ("@needs_call", "монтаж свадебного видео", "давайте лучше созвонимся, обсудим голосом"),
]


async def main():
    store = InMemoryStore()
    engine = Engine(store, MockLLM(), sender=PrintSender(), notifier=PrintNotifier())

    print("=" * 70)
    print("VendorFlow — оффлайн-демо (реальный движок, заглушки вместо Telegram/Google/LLM)")
    print("=" * 70)

    print("\n[1] Менеджер ставит вендоров в очередь (флаг «Запустить»):")
    for tg, task, _ in SCENARIO:
        store.add_contractor_if_absent(Contractor(telegram=tg, task_brief=task, launch=True))
        print(f"    + {tg} — {task}")

    print("\n[2] Планировщик сам пишет каждому первым:\n")
    while await engine.contact_next_ready():
        pass

    print("[3] Подрядчики отвечают — агент анализирует и решает:\n")
    for tg, _, reply in SCENARIO:
        print(f"   📩 {tg} → агент: {reply}")
        await engine.handle_incoming(tg, reply, message_id=100)

    print("=" * 70)
    print("ИТОГ В ТАБЛИЦЕ (в памяти):")
    print("=" * 70)
    for c in store.rows.values():
        print(f"  {c.telegram:<14} | {STATUS_LABELS[c.status]:<11} | "
              f"цена={c.price or '—'} | срок={c.deadline or '—'} | условия={c.conditions or '—'}")


if __name__ == "__main__":
    asyncio.run(main())
