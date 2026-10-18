"""Аккаунты пачкой: удаление и отвязка одним запросом, разбор строк импорта.
TestClient недоступен — зовём функции роутера."""
import pytest
from fastapi import HTTPException

from farm import accounts
from farm.api import accounts as accounts_api


@pytest.fixture
def acc_file(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", path)
    monkeypatch.setattr(accounts, "_items", None)
    return path


def _make(n, serial=""):
    return [accounts.create({"platform": "vk", "login": f"u{i}", "password": "p",
                             "serial": serial}) for i in range(n)]


def test_удаление_пачкой_одним_сохранением(acc_file, monkeypatch):
    items = _make(5)
    saves = []
    real = accounts._save
    monkeypatch.setattr(accounts, "_save", lambda: (saves.append(1), real()))
    res = accounts_api.delete_accounts(ids=[items[0]["id"], items[2]["id"], items[4]["id"]])
    assert res == {"ok": True, "deleted": 3}
    assert len(saves) == 1
    left = {a["login"] for a in accounts.all_accounts()}
    assert left == {"u1", "u3"}


def test_удаление_пачкой_незнакомые_и_повторы(acc_file):
    items = _make(2)
    res = accounts_api.delete_accounts(ids=[items[0]["id"], items[0]["id"], "nope"])
    assert res["deleted"] == 1
    assert [a["login"] for a in accounts.all_accounts()] == ["u1"]


def test_удаление_пачкой_пустой_список_ничего_не_пишет(acc_file):
    _make(1)
    acc_file.unlink()
    assert accounts_api.delete_accounts(ids=[])["deleted"] == 0
    assert not acc_file.exists()


def test_удаление_пачкой_проверяет_ids(acc_file):
    with pytest.raises(HTTPException) as e:
        accounts_api.delete_accounts(ids=[1, 2])
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        accounts_api.delete_accounts(ids="abc")


def test_отвязка_пачкой(acc_file):
    bound = _make(2, serial="S1")
    free = _make(1)
    res = accounts_api.unbind_accounts(ids=[a["id"] for a in bound + free])
    assert res == {"ok": True, "unbound": 2}
    assert all(not a["serial"] for a in accounts.all_accounts())


def test_список_без_паролей_после_пачки(acc_file):
    items = _make(3)
    accounts_api.delete_accounts(ids=[items[0]["id"]])
    assert all("password" not in a for a in accounts_api.list_accounts())


@pytest.mark.parametrize("line,login,password,proxy", [
    ("a:b", "a", "b", None),
    ("a;b;1.2.3.4:80", "a", "b", "1.2.3.4:80"),
    ("a\tb\t1.2.3.4:80", "a", "b", "1.2.3.4:80"),
    ("a:b:1.2.3.4:80", "a", "b", "1.2.3.4:80"),
    ("a,b", "a", "b", None),
    ("a:p,w", "a", "p,w", None),
    ("a", "a", None, None),
])
def test_разбор_строк(line, login, password, proxy):
    row = accounts.parse_lines(line, "vk")[0]
    assert row["login"] == login
    assert row.get("password") == password
    assert row.get("proxy") == proxy


def test_импорт_отчёт_дубли_и_без_пароля(acc_file):
    accounts.create({"platform": "vk", "login": "Old", "password": "x"})
    res = accounts_api.import_accounts(text="old:1\nnew:2\nNEW:3\nnopass\n", platform="vk")
    assert res["count"] == 1 and res["duplicates"] == 2 and res["bad_lines"] == [4]
