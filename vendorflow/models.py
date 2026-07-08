"""Модель состояния подрядчика — единственный источник правды о диалоге.

Таблица теперь двухслойная: видимые человеку столбцы (кому, что за задача, флаг
«Запустить», статус и собранные данные) плюс один служебный столбец `_meta` с JSON,
куда сложена вся машинерия движка (история, счётчики, таймстемпы, id). Менеджер работает
с видимыми столбцами, `_meta` можно свернуть.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .normalize import normalize_telegram


class Status(str, Enum):
    ready_to_contact = "ready_to_contact"
    first_message_sent = "first_message_sent"
    waiting_reply = "waiting_reply"
    needs_human_review = "needs_human_review"
    completed = "completed"
    stopped = "stopped"  # менеджер вручную выключил подрядчика


# Человекочитаемые подписи статусов в таблице (менеджеру, не enum-строки).
STATUS_LABELS = {
    Status.ready_to_contact: "в очереди",
    Status.first_message_sent: "пишем",
    Status.waiting_reply: "ждём ответа",
    Status.needs_human_review: "на проверку",
    Status.completed: "готово",
    Status.stopped: "стоп",
}
_STATUS_FROM_LABEL = {v: k for k, v in STATUS_LABELS.items()}

# Заголовки столбцов = ключи чтения из get_all_records. Первые четыре заполняет менеджер.
COL_TELEGRAM = "Telegram"
COL_CATEGORY = "Категория"
COL_TASK = "Задача"
COL_LAUNCH = "Запустить"
COL_STATUS = "Статус"
COL_PRICE = "Цена"
COL_DEADLINE = "Срок"
COL_CONDITIONS = "Условия"
COL_SUMMARY = "Резюме"
COL_REVIEW = "Стоп-причина"
COL_UPDATED = "Обновлено"
COL_META = "_meta"

COLUMNS = [
    COL_TELEGRAM, COL_CATEGORY, COL_TASK, COL_LAUNCH, COL_STATUS,
    COL_PRICE, COL_DEADLINE, COL_CONDITIONS, COL_SUMMARY, COL_REVIEW,
    COL_UPDATED, COL_META,
]

_TRUTHY = {"true", "да", "yes", "1", "on", "✓", "✔", "x", "y"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_launch(raw) -> bool:
    """Флаг «Запустить»: срабатывает и на чекбокс (TRUE), и на текст ДА/да/1/✓."""
    return str(raw or "").strip().lower() in _TRUTHY


@dataclass
class Contractor:
    telegram: str
    name: str = ""
    category: str = ""
    task_brief: str = ""
    launch: bool = False           # флаг менеджера «отправлять этому вендору»
    status: Status = Status.ready_to_contact

    price: str | None = None
    deadline: str | None = None
    conditions: str | None = None
    prepayment: str | None = None
    availability: str | None = None

    contractor_questions: list[str] = field(default_factory=list)
    requested_materials: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=lambda: ["price", "deadline", "conditions"])
    confidence: float = 0.0

    review_reason: str = ""
    manager_summary: str = ""
    history: list[dict] = field(default_factory=list)  # [{from, text, ts}]

    last_inbound_message_id: int = 0
    first_message_sent_at: str = ""
    last_outbound_at: str = ""
    last_inbound_at: str = ""
    messages_sent_date: str = ""   # дата, к которой относится счётчик
    messages_sent_today: int = 0

    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @property
    def telegram_key(self) -> str:
        return normalize_telegram(self.telegram)

    @property
    def telegram_url(self) -> str:
        """Кликабельная ссылка на чат вендора для уведомлений менеджеру."""
        key = self.telegram_key
        if not key:
            return ""
        if key.lstrip("-").isdigit():   # числовой id — открываем профиль
            return f"tg://user?id={key}"
        return f"https://t.me/{key}"

    def add_message(self, sender: str, text: str) -> None:
        self.history.append({"from": sender, "text": text, "ts": now_iso()})

    def last_our_message(self) -> str | None:
        for m in reversed(self.history):
            if m["from"] == "assistant":
                return m["text"]
        return None

    def _meta(self) -> dict:
        """Вся машинерия движка — прячется в один JSON-столбец, менеджеру не мешает."""
        return {
            "name": self.name,
            "prepayment": self.prepayment,
            "availability": self.availability,
            "contractor_questions": self.contractor_questions,
            "requested_materials": self.requested_materials,
            "risk_flags": self.risk_flags,
            "missing_fields": self.missing_fields,
            "confidence": self.confidence,
            "history": self.history,
            "last_inbound_message_id": self.last_inbound_message_id,
            "first_message_sent_at": self.first_message_sent_at,
            "last_outbound_at": self.last_outbound_at,
            "last_inbound_at": self.last_inbound_at,
            "messages_sent_date": self.messages_sent_date,
            "messages_sent_today": self.messages_sent_today,
            "created_at": self.created_at,
        }

    def to_row(self) -> list[str]:
        self.updated_at = now_iso()
        values = {
            COL_TELEGRAM: self.telegram,
            COL_CATEGORY: self.category,
            COL_TASK: self.task_brief,
            COL_LAUNCH: "TRUE" if self.launch else "",
            COL_STATUS: STATUS_LABELS.get(self.status, self.status.value),
            COL_PRICE: self.price or "",
            COL_DEADLINE: self.deadline or "",
            COL_CONDITIONS: self.conditions or "",
            COL_SUMMARY: self.manager_summary,
            COL_REVIEW: self.review_reason,
            COL_UPDATED: self.updated_at,
            COL_META: json.dumps(self._meta(), ensure_ascii=False),
        }
        return [str(values.get(col, "")) for col in COLUMNS]

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Contractor":
        def _txt(v):
            return v if v not in ("", None) else None

        meta = {}
        raw_meta = row.get(COL_META)
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}

        c = cls(telegram=str(row.get(COL_TELEGRAM, "")))
        c.category = str(row.get(COL_CATEGORY, ""))
        c.task_brief = str(row.get(COL_TASK, ""))
        c.launch = is_launch(row.get(COL_LAUNCH))
        c.status = _parse_status(row.get(COL_STATUS))
        c.price = _txt(row.get(COL_PRICE))
        c.deadline = _txt(row.get(COL_DEADLINE))
        c.conditions = _txt(row.get(COL_CONDITIONS))
        c.manager_summary = str(row.get(COL_SUMMARY, ""))
        c.review_reason = str(row.get(COL_REVIEW, ""))
        c.updated_at = str(row.get(COL_UPDATED) or now_iso())

        # из служебного JSON
        c.name = meta.get("name", "")
        c.prepayment = _txt(meta.get("prepayment"))
        c.availability = _txt(meta.get("availability"))
        c.contractor_questions = meta.get("contractor_questions") or []
        c.requested_materials = meta.get("requested_materials") or []
        c.risk_flags = meta.get("risk_flags") or []
        c.missing_fields = meta.get("missing_fields") or ["price", "deadline", "conditions"]
        c.confidence = float(meta.get("confidence") or 0.0)
        c.history = meta.get("history") or []
        c.last_inbound_message_id = int(meta.get("last_inbound_message_id") or 0)
        c.first_message_sent_at = meta.get("first_message_sent_at", "")
        c.last_outbound_at = meta.get("last_outbound_at", "")
        c.last_inbound_at = meta.get("last_inbound_at", "")
        c.messages_sent_date = meta.get("messages_sent_date", "")
        c.messages_sent_today = int(meta.get("messages_sent_today") or 0)
        c.created_at = meta.get("created_at") or now_iso()
        return c


def _parse_status(raw) -> Status:
    """Человеческую подпись → enum. Пустой статус (новая строка от менеджера) = в очереди."""
    label = str(raw or "").strip().lower()
    if not label:
        return Status.ready_to_contact
    if label in _STATUS_FROM_LABEL:
        return _STATUS_FROM_LABEL[label]
    try:  # на случай, если в ячейке осталась enum-строка
        return Status(label)
    except ValueError:
        return Status.ready_to_contact
