"""Конфигурация из окружения. Всё, что связано с безопасностью и лимитами, живёт здесь."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


@dataclass(frozen=True)
class Config:
    # LLM
    llm_provider: str = os.getenv("LLM_PROVIDER", "claude-code")  # "claude-code" (без ключа, локальный CLI) | "openai"
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")  # можно OpenRouter и др. совместимые
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o")          # модель для провайдера openai
    # Разные модели под разные вызовы: анализ трезвее и дешевле, сочинение — качественнее.
    # Для Claude тир модели (haiku<sonnet<opus) и есть рычаг «эффорта».
    claude_model_analyze: str = os.getenv("CLAUDE_MODEL_ANALYZE", "haiku")
    claude_model_compose: str = os.getenv("CLAUDE_MODEL_COMPOSE", "sonnet")

    # Google Sheets
    google_credentials_path: str = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/google_credentials.json")
    sheet_name: str = os.getenv("SHEET_NAME", "VendorFlow")
    sheet_id: str = os.getenv("SHEET_ID", "")  # если задан — открываем по ID, надёжнее чем по имени

    # Telethon
    tg_api_id: int = _int("TG_API_ID", 0)
    tg_api_hash: str = os.getenv("TG_API_HASH", "")
    tg_session: str = os.getenv("TG_SESSION", "config/vendorflow.session")
    tg_phone: str = os.getenv("TG_PHONE", "")  # телефон аккаунта для одноразового логина (auth.py)

    # Бот менеджера
    manager_bot_token: str = os.getenv("MANAGER_BOT_TOKEN", "")
    manager_chat_id: int = _int("MANAGER_CHAT_ID", 0)

    # Safety
    dry_run: bool = _bool("DRY_RUN", True)          # по умолчанию ничего реально не отправляем
    kill_switch: bool = _bool("KILL_SWITCH", False) # мгновенная остановка всей отправки
    test_run: bool = _bool("TEST_RUN", False)       # тестовый прогон: обходит рабочие часы, паузы и лимиты (но не kill_switch)

    # Планировщик
    work_hours_start: int = _int("WORK_HOURS_START", 10)
    work_hours_end: int = _int("WORK_HOURS_END", 18)
    max_new_contacts_per_day: int = _int("MAX_NEW_CONTACTS_PER_DAY", 15)
    max_messages_per_contact_per_day: int = _int("MAX_MESSAGES_PER_CONTACT_PER_DAY", 3)

    # Паузы, секунды (min, max)
    pause_before_first: tuple[int, int] = (60, 300)   # 1-5 мин перед первым сообщением
    pause_before_reply: tuple[int, int] = (60, 420)   # 1-7 мин перед ответом
    timezone: str = os.getenv("TZ", "Europe/Moscow")

    def credentials_abspath(self) -> Path:
        p = Path(self.google_credentials_path)
        return p if p.is_absolute() else ROOT / p

    def sheet_url(self, row: int | None = None) -> str:
        """Ссылка на таблицу (и конкретную строку) для уведомлений менеджеру."""
        if not self.sheet_id:
            return ""
        base = f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit"
        return f"{base}#gid=0&range=A{row}" if row else base


config = Config()
