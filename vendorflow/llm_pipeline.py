"""Два раздельных вызова LLM: сначала анализ+стоп-правила (холодный), потом текст (тёплый).

Разделение сделано намеренно: если решать "останавливаться ли" и сочинять ответ в одном
вызове, модель склонна продолжить диалог ради связного ответа. Анализатор не видит задачи
"написать красиво" и решает трезвее.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import config, ROOT
from .models import Contractor
from .normalize import similar

_PROMPTS = ROOT / "prompts"


def _load(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8")


def _find_claude() -> str | None:
    path = shutil.which("claude")
    if path:
        return path
    # на Windows claude часто ставится как .cmd в npm-global и не всегда в PATH
    exts = (".cmd", ".exe", "") if sys.platform == "win32" else ("", ".cmd", ".exe")
    npm_global = Path.home() / "AppData" / "Roaming" / "npm"
    for ext in exts:
        candidate = npm_global / f"claude{ext}"
        if candidate.exists():
            return str(candidate)
    return None


def _extract_json(text: str) -> dict:
    """Достаём JSON из ответа модели: находим внешние {}, срезаем висячие запятые."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"нет JSON в ответе: {text[:200]!r}")
    return json.loads(re.sub(r",\s*([}\]])", r"\1", text[start:end + 1]))


@dataclass
class Analysis:
    stop: bool
    completed: bool
    stop_reason: str | None
    next_missing_field: str | None
    extracted: dict
    manager_summary: str
    reason: str


class LLMPipeline:
    def __init__(self, client=None):
        self.provider = config.llm_provider
        self._client = client  # openai.OpenAI; создаём лениво, чтобы claude-code работал без ключа
        self._extract_prompt = _load("extract_and_check.md")
        self._compose_prompt = _load("compose_reply.md")

    def _chat_json(self, system: str, user: str, temperature: float, claude_model: str) -> dict:
        if self.provider == "claude-code":
            return self._chat_json_via_cli(system, user, claude_model)
        return self._chat_json_via_api(system, user, temperature)

    def _chat_json_via_api(self, system: str, user: str, temperature: float) -> dict:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=config.openai_api_key, base_url=config.llm_base_url)
        resp = self._client.chat.completions.create(
            model=config.llm_model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return json.loads(resp.choices[0].message.content)

    def _chat_json_via_cli(self, system: str, user: str, model: str) -> dict:
        """Локальный claude CLI: без API-ключа, temperature не поддерживается (для MVP ок)."""
        binary = _find_claude()
        if not binary:
            raise RuntimeError("claude CLI не найден в PATH — задай LLM_PROVIDER=openai и OPENAI_API_KEY")

        prompt = f"{system}\n\n{user}"
        if sys.platform == "win32" and binary.lower().endswith((".cmd", ".bat")):
            exe = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
            args = [exe, "/c", binary, "-p", "--output-format", "json", "--model", model]
        else:
            args = [binary, "-p", "--output-format", "json", "--model", model]

        proc = subprocess.run(args, input=prompt.encode(), capture_output=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI код {proc.returncode}: {proc.stderr.decode(errors='replace')[:300]}")
        data = json.loads(proc.stdout.decode(errors="replace"))
        return _extract_json(data.get("result", "{}"))

    def _context(self, c: Contractor) -> str:
        payload = {
            "task_brief": c.task_brief,
            "contractor": {"name": c.name, "category": c.category},
            "known_data": {
                "price": c.price,
                "deadline": c.deadline,
                "conditions": c.conditions,
                "prepayment": c.prepayment,
                "availability": c.availability,
            },
            "missing_fields": c.missing_fields,
            "conversation_history": [
                {"from": m["from"], "text": m["text"]} for m in c.history
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def analyze(self, c: Contractor) -> Analysis:
        """Холодный вызов: извлечение данных + стоп-правила. Текста подрядчику здесь нет."""
        data = self._chat_json(self._extract_prompt, self._context(c),
                               temperature=0.0, claude_model=config.claude_model_analyze)
        return Analysis(
            stop=bool(data.get("stop")),
            completed=bool(data.get("completed")),
            stop_reason=data.get("stop_reason"),
            next_missing_field=data.get("next_missing_field"),
            extracted=data.get("extracted_data", {}),
            manager_summary=data.get("manager_summary", ""),
            reason=data.get("reason", ""),
        )

    def compose(self, c: Contractor, next_missing_field: str | None) -> str:
        """Тёплый вызов: только текст. Вызывается лишь если analyze разрешил продолжать."""
        ctx = self._context(c)
        hint = f'\n\nnext_missing_field = {next_missing_field}'
        data = self._chat_json(self._compose_prompt, ctx + hint,
                               temperature=0.7, claude_model=config.claude_model_compose)
        msg = (data.get("message_to_contractor") or "").strip()

        # анти-повтор: если получилось почти то же, что уже писали — не отправляем
        if similar(msg, c.last_our_message()):
            return ""
        return msg
