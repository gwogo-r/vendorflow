from vendorflow.models import (
    Contractor, Status, COLUMNS, COL_META, COL_TELEGRAM, is_launch,
)


def _as_row(c: Contractor) -> dict:
    return dict(zip(COLUMNS, c.to_row()))


def test_to_row_from_row_roundtrip():
    c = Contractor(telegram="@vasya", category="дизайн", task_brief="лого",
                   launch=True, status=Status.waiting_reply)
    c.price = "5000"
    c.deadline = "неделя"
    c.add_message("assistant", "привет")
    c.last_inbound_message_id = 42
    c.first_message_sent_at = "2026-07-08T10:00:00+00:00"

    c2 = Contractor.from_row(_as_row(c))
    assert c2.telegram_key == "vasya"
    assert c2.category == "дизайн"
    assert c2.task_brief == "лого"
    assert c2.launch is True
    assert c2.status == Status.waiting_reply
    assert c2.price == "5000"
    assert c2.deadline == "неделя"
    assert len(c2.history) == 1
    assert c2.last_inbound_message_id == 42
    assert c2.first_message_sent_at == "2026-07-08T10:00:00+00:00"


def test_machinery_lives_in_meta_not_visible_columns():
    c = Contractor(telegram="@x")
    c.add_message("assistant", "секретная история")
    row = _as_row(c)
    assert "секретная история" in row[COL_META]      # история спрятана в _meta
    assert "секретная история" not in row[COL_TELEGRAM]


def test_launch_flag_variants():
    assert all(is_launch(v) for v in ["TRUE", "да", "ДА", "✓", "1", "yes"])
    assert not any(is_launch(v) for v in ["", "нет", None, "0"])


def test_manager_row_empty_status_is_queue():
    # менеджер добавил строку руками: телега + задача + галочка, статус пустой
    c = Contractor.from_row({"Telegram": "@new", "Задача": "смонтировать", "Запустить": "TRUE"})
    assert c.launch is True
    assert c.status == Status.ready_to_contact
    assert not c.first_message_sent_at  # ещё не писали — попадёт в очередь
