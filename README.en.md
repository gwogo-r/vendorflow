# VendorFlow

[Русский](README.md) · **English**

An AI agent that, **on the manager's command, messages contractors first on Telegram**, runs a short business conversation, collects price, deadlines and terms, records everything in Google Sheets, and **stops for manual review when a human decision is needed**. It writes naturally — during working hours, with pauses, like a real person.

A working MVP prototype built for an AI-integrator test assignment.

---

## What it does (in 30 seconds)

1. The manager adds a vendor to the Google Sheet: **handle, task**, and ticks **"Launch"**.
2. The scheduler messages the contractor first — on its own, during working hours, with human-like pauses.
3. The agent runs the dialogue: one question at a time, **extracts price / deadline / terms**, writes the result into the same row.
4. If everything is collected — marks it **"done"**. If a human is needed (a call is requested, payment, a contract, or the price looks unrealistic) — it **stops, marks "needs review" and pings the manager in the Telegram bot**, without writing anything to the contractor.

The sheet is the single entry point and the whole CRM: one row = one vendor.

| Telegram | Task | Launch | Status | Price | Deadline | Terms |
|---|---|---|---|---|---|---|
| @vendor_a | 60s clip | ✅ | waiting reply | 5000 | 1 week | — |
| @vendor_b | shorts cutdown | ✅ | done | 8000 | 3 days | 50% upfront |

---

## Try it with nothing (one command, no keys, no Telegram)

```bash
pip install -r requirements.txt
python demo.py
```

`demo.py` runs the **real engine** against three contractors, but with stubs instead of Telegram / Google / LLM — you see the agent message first, collect data, and stop for manual review in two different cases. No credentials required.

---

## How it works (key decisions)

| Module | File | Responsibility |
|--------|------|----------------|
| Orchestrator | `vendorflow/engine.py` | status transitions, all decision logic |
| Scheduler | `vendorflow/scheduler.py` | working hours, pauses, limits, kill switch — plain code, not the LLM |
| LLM analysis | `vendorflow/llm_pipeline.py` → `analyze()` | data extraction + stop rules, temperature=0, JSON only |
| LLM text | `vendorflow/llm_pipeline.py` → `compose()` | drafts the message, called only if analysis allows |
| Storage | `vendorflow/state_store.py` | Google Sheets, dedup, idempotency |
| Sending | `vendorflow/telegram_client.py` | Telethon (messages first), typing simulation |
| Manager bot | `vendorflow/manager_bot.py` | `/contact`, `/status`, `/stop`, notifications |

**Why two separate LLM calls.** If "should we continue" and drafting the reply happen in one call, the model tends to keep the dialogue going just to produce coherent text. A cold analyzer (temperature=0), not tasked with "write nicely", judges more soberly; the text is composed separately and only once analysis has allowed it.

**Why the scheduler is code, not the LLM.** The model has no reliable clock or memory between calls. "Whether and when to send" is decided by code: working hours Mon–Fri 10:00–18:00, pauses of 1–5 min, daily limits. The LLM only proposes a message and a status.

**The LLM provider is abstract.** Default is `claude-code` (local CLI, no API key); switches to OpenAI / OpenRouter with one variable in `.env`. Different models for different jobs: fast for analysis, higher quality for composing.

---

## Safety

- `DRY_RUN=true` (default) — nothing is sent to contractors, everything goes to logs.
- `KILL_SWITCH=true` — instantly mutes all sending.
- `TEST_RUN=true` — for debugging, bypasses working hours/pauses/limits (but **not** the kill switch).
- Stop rules (call, payment/details, contract, dissatisfaction, anomalies, model uncertainty) → status `needs_human_review`, nothing to the contractor, the manager is called.
- Dedup: one contractor = one row by normalized telegram key; the first message is idempotent.

---

## Full run (with real Telegram and Google)

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in the keys (see comments in the file)
python auth.py            # one-time Telethon login (saves the session)
pytest -q                 # run the tests
python main.py            # live mode (safe while DRY_RUN=true)
```

Needed in `.env`: access to the Google Sheet (`SHEET_ID` + service account), `TG_API_ID`/`TG_API_HASH` (my.telegram.org), `MANAGER_BOT_TOKEN`/`MANAGER_CHAT_ID`. An OpenAI key is optional — by default it runs via the local `claude-code`.

## Contractor statuses

`queued → messaging → waiting reply → (needs review | done)`, plus `stopped` — manual switch-off by the manager.
