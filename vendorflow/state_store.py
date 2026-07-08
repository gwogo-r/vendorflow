"""Google Sheets как хранилище состояния. Здесь же живёт дедупликация подрядчиков.

Одна строка таблицы = один подрядчик, ключ — нормализованный telegram (см. normalize).
Дубли не создаём: upsert по ключу. Отправка первого сообщения идемпотентна через
first_message_sent_at.
"""

from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials

from .config import config
from .models import Contractor, Status, COLUMNS, COL_TELEGRAM, now_iso
from .normalize import normalize_telegram

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class StateStore:
    def __init__(self):
        creds = Credentials.from_service_account_file(
            str(config.credentials_abspath()), scopes=_SCOPES
        )
        self.gc = gspread.authorize(creds)
        self.sheet = self._open_or_create()
        self._ensure_header()

    def _open_or_create(self):
        if config.sheet_id:
            return self.gc.open_by_key(config.sheet_id).sheet1
        try:
            sh = self.gc.open(config.sheet_name)
        except gspread.SpreadsheetNotFound:
            sh = self.gc.create(config.sheet_name)
        return sh.sheet1

    def _ensure_header(self):
        header = self.sheet.row_values(1)
        if header != COLUMNS:
            self.sheet.update("A1", [COLUMNS])

    # чтение

    def _all_rows(self) -> list[dict]:
        return self.sheet.get_all_records()  # первая строка — заголовок

    def get(self, telegram: str) -> tuple[int, Contractor] | tuple[None, None]:
        """Ищем подрядчика по нормализованному telegram-ключу. Возвращаем (номер строки, объект)."""
        key = normalize_telegram(telegram)
        for i, row in enumerate(self._all_rows(), start=2):  # +1 заголовок, +1 к 0-based
            if normalize_telegram(row.get(COL_TELEGRAM, "")) == key:
                return i, Contractor.from_row(row)
        return None, None

    def list_launch_pending(self) -> list[tuple[int, Contractor]]:
        """Строки, готовые к первому контакту: флаг «Запустить» стоит, а первого сообщения ещё не было."""
        out = []
        for i, row in enumerate(self._all_rows(), start=2):
            c = Contractor.from_row(row)
            if c.launch and not c.first_message_sent_at and c.status not in (Status.stopped, Status.completed):
                out.append((i, c))
        return out

    def count_contacted_today(self) -> int:
        """Сколько подрядчиков реально получили первое сообщение сегодня — для дневного лимита."""
        today = now_iso()[:10]
        n = 0
        for row in self._all_rows():
            c = Contractor.from_row(row)
            if c.first_message_sent_at[:10] == today:
                n += 1
        return n

    # запись

    def upsert(self, c: Contractor) -> int:
        """Создаём или обновляем строку по ключу. Дублей не будет."""
        row_num, existing = self.get(c.telegram_key)
        values = c.to_row()
        if row_num is None:
            self.sheet.append_row(values, value_input_option="RAW")
            row_num, _ = self.get(c.telegram_key)
            return row_num
        self._write_row(row_num, values)
        return row_num

    def _write_row(self, row_num: int, values: list[str]):
        last_col = _col_letter(len(COLUMNS))
        self.sheet.update(f"A{row_num}:{last_col}{row_num}", [values], value_input_option="RAW")

    def add_contractor_if_absent(self, c: Contractor) -> bool:
        """Для загрузки менеджером: не перезаписываем существующего. True если добавлен новый."""
        row_num, _ = self.get(c.telegram_key)
        if row_num is not None:
            return False
        self.upsert(c)
        return True


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
