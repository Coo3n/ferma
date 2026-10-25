"""Варианты текста: разбор, подсчёт, выбор, предупреждение."""
import random

from farm import phrases


def test_no_variants_returns_text_unchanged():
    for text in ("", "привет", "{}", "{один}", '{"a": 1}', "цена 5}", "a|b"):
        assert phrases.pick(text) == text, text
        assert phrases.count(text) == 1, text


def test_picks_one_of_the_variants():
    got = {phrases.pick("{привет|здравствуй|хай}") for _ in range(60)}
    assert got <= {"привет", "здравствуй", "хай"}
    assert len(got) == 3        # за 60 попыток выпадают все три


def test_counts_combinations():
    assert phrases.count("{привет|хай}, {друг|дружище}") == 4
    assert phrases.count("{a|b|c}") == 3
    assert phrases.count("{a|{b|c}}") == 3


def test_nested_groups_expand():
    got = {phrases.pick("{привет|добрый {день|вечер}}") for _ in range(80)}
    assert got <= {"привет", "добрый день", "добрый вечер"}
    assert len(got) == 3


def test_escaping_works_inside_variants():
    assert phrases.pick(r"{a\|b|c}") in ("a|b", "c")
    assert phrases.pick(r"{скидка \{5\}|даром}") in ("скидка {5}", "даром")


def test_text_without_variants_is_never_touched():
    """Экранирование нужно лишь рядом с вариантами: текста без них оно не
    касается, иначе набранное человеком «C:\\папка» теряло бы слеш."""
    for text in (r"цена \{5\}", r"C:\папка", r"\{a\|b\}"):
        assert phrases.pick(text) == text, text
        assert phrases.count(text) == 1, text


def test_unclosed_brace_is_literal_not_a_crash():
    assert phrases.pick("{привет|здравствуй") == "{привет|здравствуй"
    assert "не закрыта" in phrases.check("{привет|здравствуй")


def test_check_silent_on_good_and_plain_text():
    assert phrases.check("{привет|здравствуй}") == ""
    assert phrases.check("обычный текст") == ""
    assert phrases.check("") == ""


def test_count_is_capped():
    assert phrases.count("{a|b}" * 40) == phrases.COUNT_MAX


def test_deeper_than_max_depth_stays_literal():
    text = "{a|" + "{b|" * phrases.MAX_DEPTH + "c" + "}" * phrases.MAX_DEPTH + "}"
    assert phrases.pick(text, random.Random(1))      # не падает
    assert phrases.count(text) < phrases.COUNT_MAX
