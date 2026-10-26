"""Пакетный ввод «каждому своё»: строки → телефоны, части строки, шаблон."""
import random

import pytest

from farm import lines
from farm.api import bulk


def test_clean_rows_from_text_and_list():
    assert lines.clean_rows("a\n\n  b \r\nc") == ["a", "b", "c"]
    assert lines.clean_rows([" x ", "", "y"]) == ["x", "y"]
    assert lines.clean_rows(None) == []


def test_clean_rows_limit():
    assert len(lines.clean_rows([str(i) for i in range(9000)])) == lines.MAX_ROWS


def test_split_row():
    assert lines.split_row("ivan;pass1;x", ";") == ["ivan", "pass1", "x"]
    assert lines.split_row(" a , b ", ",") == ["a", "b"]
    assert lines.split_row("whole line", "") == ["whole line"]


def test_render_template():
    assert lines.render("{1}@mail.ru", ["ivan", "p"]) == "ivan@mail.ru"
    assert lines.render("{2}/{1}", ["a", "b"]) == "b/a"
    assert lines.render("{3}", ["a"]) == ""            # части нет — пусто, а не падение
    assert lines.render("", ["whole"]) == "whole"


def test_assign_order_leaves_extra_phones_without_text():
    got = lines.assign(["A", "B", "C"], ["1", "2"], "order")
    assert got == {"A": "1", "B": "2", "C": None}


def test_assign_cycle_repeats():
    got = lines.assign(["A", "B", "C", "D", "E"], ["1", "2"], "cycle")
    assert [got[s] for s in "ABCDE"] == ["1", "2", "1", "2", "1"]


def test_assign_random_uses_only_given_rows():
    got = lines.assign(["A", "B", "C", "D"], ["x", "y"], "random", random.Random(3))
    assert set(got.values()) <= {"x", "y"}


def test_assign_unknown_mode():
    with pytest.raises(ValueError):
        lines.assign(["A"], ["1"], "weird")


def test_assign_without_rows():
    assert lines.assign(["A", "B"], [], "order") == {"A": None, "B": None}


@pytest.fixture
def sent(monkeypatch):
    got = []
    monkeypatch.setattr(bulk, "_online", lambda serials: list(serials))
    monkeypatch.setitem(bulk.ACTIONS, "text",
                        lambda serial, p: got.append((serial, p["value"], p.get("clear"))))
    return got


def test_endpoint_sends_each_phone_its_line(sent):
    res = bulk.text_lines(serials=["A", "B"], lines=["one", "two"], mode="order",
                          separator="", template="", clear=False)
    assert sorted(sent) == [("A", "one", False), ("B", "two", False)]
    assert res["done"] == 2 and res["failed"] == 0


def test_endpoint_template_and_separator(sent):
    bulk.text_lines(serials=["A"], lines=["ivan;secret"], mode="order",
                    separator=";", template="{1}@x.ru", clear=True)
    assert sent == [("A", "ivan@x.ru", True)]


def test_endpoint_reports_phones_without_a_line(sent):
    res = bulk.text_lines(serials=["A", "B", "C"], lines=["one"], mode="order",
                          separator="", template="", clear=False)
    assert [s for s, _, _ in sent] == ["A"]
    assert res["failed"] == 2
    assert "не хватило" in res["results"]["B"]["error"]


def test_endpoint_rejects_empty_file(sent):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        bulk.text_lines(serials=["A"], lines=["", "  "], mode="order",
                        separator="", template="", clear=False)
    assert e.value.status_code == 400


def test_endpoint_empty_rendered_text_is_failure_and_not_sent(sent):
    res = bulk.text_lines(serials=["A", "B"], lines=["one;x", "two"], mode="order",
                          separator=";", template="{2}", clear=True)
    assert sent == [("A", "x", True)]              # у B части {2} нет: пустое не отправлено
    assert res["failed"] == 1 and res["results"]["B"]["error"] == "пустой текст"
