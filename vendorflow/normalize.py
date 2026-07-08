"""Нормализация telegram-идентификаторов и текста — основа дедупликации."""

from __future__ import annotations

import re

_TG_PREFIXES = ("https://t.me/", "http://t.me/", "t.me/", "@")


def normalize_telegram(raw: str | int | None) -> str:
    """Приводим любой вид контакта к единому ключу.

    @Ivan, https://t.me/ivan, t.me/ivan, ivan → 'ivan'.
    Числовой chat_id остаётся как есть (строкой).
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    # чистый chat_id
    if s.lstrip("-").isdigit():
        return s
    s = s.lower()
    for p in _TG_PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
    # на случай ссылки с хвостом вида ivan?start=...
    s = s.split("?", 1)[0].split("/", 1)[0]
    return s.strip()


def normalize_text(text: str | None) -> str:
    """Схлопываем пробелы, регистр и пунктуацию — для сравнения «не повторяем ли мы себя»."""
    if not text:
        return ""
    text = re.sub(r"[^\w\s]", " ", text)  # знаки препинания в пробел, чтобы 'цене?' == 'цене'
    return re.sub(r"\s+", " ", text).strip().lower()


def similar(a: str | None, b: str | None, threshold: float = 0.9) -> bool:
    """Грубое сравнение двух наших сообщений, чтобы не задваивать один и тот же вопрос.

    Без внешних либ: отношение общих слов. Для коротких деловых реплик достаточно.
    """
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    wa, wb = set(na.split()), set(nb.split())
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / len(wa | wb)
    return overlap >= threshold
