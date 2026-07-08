from vendorflow.normalize import normalize_telegram, similar


def test_normalize_variants_collapse_to_one_key():
    forms = ["@Ivan", "ivan", "https://t.me/ivan", "t.me/ivan", "  IVAN  ", "https://t.me/ivan?start=1"]
    keys = {normalize_telegram(f) for f in forms}
    assert keys == {"ivan"}


def test_numeric_chat_id_kept():
    assert normalize_telegram(123456789) == "123456789"
    assert normalize_telegram("-1001234") == "-1001234"


def test_empty():
    assert normalize_telegram(None) == ""
    assert normalize_telegram("") == ""


def test_similar_catches_repeated_question():
    a = "Подскажите, пожалуйста, ориентир по цене?"
    b = "подскажите пожалуйста ориентир по цене"
    assert similar(a, b)


def test_similar_distinguishes_different_questions():
    a = "Сориентируете по цене?"
    b = "А какие сроки по работе?"
    assert not similar(a, b)
