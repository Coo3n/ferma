"""Контакты пакетом: номера, файл, shell-скрипты, ответы телефона."""
import random

import pytest

from farm import contacts
from farm.api import screen


def test_generate_unique_numbers_with_prefix_and_length():
    nums = contacts.generate("+7999", 11, 50, random.Random(1))
    assert len(nums) == len(set(nums)) == 50
    assert all(n.startswith("+7999") and len(n.lstrip("+")) == 11 for n in nums)


@pytest.mark.parametrize("prefix,length,count", [
    ("+7abc", 11, 5), ("+7999", 4, 5), ("+7999", 20, 5), ("+7999", 11, 0), ("+7999", 11, 5000),
    ("+79991234567", 11, 5),          # префикс уже длиной с номер — нечему случайничать
])
def test_generate_rejects_bad_input(prefix, length, count):
    with pytest.raises(ValueError):
        contacts.generate(prefix, length, count)


def test_generate_cannot_exceed_possible_numbers():
    with pytest.raises(ValueError):
        contacts.generate("+799912345", 11, 500)         # свободно две цифры — максимум 100


def test_parse_file_formats_and_skips():
    text = "+79991112233\nИван;+7 (999) 222-33-44\nМария, 89993334455\n\nмусор\n12\n"
    items, skipped = contacts.parse_file(text)
    assert items == [
        {"name": "+79991112233", "number": "+79991112233"},
        {"name": "Иван", "number": "+79992223344"},
        {"name": "Мария", "number": "89993334455"},
    ]
    assert skipped == 2


def test_parse_file_limits_count():
    items, _ = contacts.parse_file("\n".join(f"+7999{i:07d}" for i in range(3000)))
    assert len(items) == contacts.MAX_ITEMS


def test_insert_scripts_chunk_and_contents():
    items = [{"name": f"Имя {i}", "number": f"+7999000{i:04d}"} for i in range(20)]
    scripts = contacts.insert_scripts(items, chunk=15)
    assert len(scripts) == 2
    first = scripts[0]
    assert first.count("content://com.android.contacts/raw_contacts") >= 15
    assert "vnd.android.cursor.item/name" in first and "vnd.android.cursor.item/phone_v2" in first
    assert "+79990000000" in first


def test_insert_scripts_cannot_inject_shell():
    evil = [{"name": "x'; rm -rf /; echo '", "number": "+79991112233; reboot"}]
    script = contacts.insert_scripts(evil)[0]
    # кавычки и «;» из имени вырезаны, имя осталось безобидным текстом в кавычках
    assert "data1:s:'x rm -rf  echo'" in script
    assert "'; rm" not in script
    # буквы из номера вырезаны, команде reboot взяться неоткуда
    assert "reboot" not in script and "data1:s:'+79991112233'" in script


def test_insert_scripts_drops_contacts_with_bad_numbers():
    assert contacts.insert_scripts([{"name": "A", "number": "12"}]) == []


def test_clear_script():
    assert "content delete" in contacts.CLEAR_SCRIPT and "raw_contacts" in contacts.CLEAR_SCRIPT


def test_check_output_raises_for_permission_denials():
    for out in ("java.lang.SecurityException: Permission Denial", "Error: permission denied", "Exception occurred"):
        with pytest.raises(RuntimeError) as e:
            contacts.check_output(out)
        assert "не даёт" in str(e.value)
    contacts.check_output("Row: 0 _id=5\n")
    contacts.check_output("")


@pytest.fixture
def shell(monkeypatch):
    calls = []
    monkeypatch.setattr(screen.adb, "shell",
                        lambda serial, cmd, timeout=None: calls.append((serial, cmd)) or "")
    return calls


def test_action_add_items(shell):
    items = [{"name": "Иван", "number": "+79991112233"}]
    res = screen.ACTIONS["contacts_add"]("S1", {"type": "contacts_add", "items": items})
    assert res == {"ok": True, "added": 1}
    assert len(shell) == 1 and "+79991112233" in shell[0][1]


def test_action_add_generated_is_different_per_phone(shell):
    body = {"type": "contacts_add", "generate": {"prefix": "+7999", "length": 11, "count": 5}}
    screen.ACTIONS["contacts_add"]("S1", body)
    screen.ACTIONS["contacts_add"]("S2", body)
    assert shell[0][1] != shell[1][1]


def test_action_add_needs_something(shell):
    with pytest.raises(ValueError):
        screen.ACTIONS["contacts_add"]("S1", {"type": "contacts_add"})
    assert shell == []


def test_action_add_stops_on_denial(monkeypatch):
    monkeypatch.setattr(screen.adb, "shell", lambda s, c, timeout=None: "java.lang.SecurityException: Permission Denial")
    with pytest.raises(RuntimeError):
        screen.ACTIONS["contacts_add"]("S1", {"items": [{"name": "A", "number": "+79991112233"}]})


def test_action_clear(shell):
    assert screen.ACTIONS["contacts_clear"]("S1", {"type": "contacts_clear"}) == {"ok": True}
    assert "content delete" in shell[0][1]
