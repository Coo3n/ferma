"""Группы быстрых фраз: очистка, лимиты, импорт/экспорт, файл, API."""
import json
import os

import pytest
from fastapi import HTTPException

from farm import backup, config, phrase_store as ps
from farm.api import phrases as api


@pytest.fixture
def pfile(tmp_path, monkeypatch):
    path = tmp_path / "phrases.json"
    monkeypatch.setattr(config, "PHRASES_FILE", path)
    return path


def test_empty_gives_default_group():
    d = ps.clean(None)
    assert len(d["groups"]) == 1 and d["groups"][0]["name"] == "Общие"
    assert d["active"] == d["groups"][0]["id"] and d["groups"][0]["items"] == []


def test_limits():
    groups = [{"id": f"g{i}", "name": "n" * 60, "items": ["x"]} for i in range(40)]
    d = ps.clean({"groups": groups})
    assert len(d["groups"]) == 30 and len(d["groups"][0]["name"]) == 40
    d = ps.clean({"groups": [{"id": "a", "name": "A", "items": [f"p{i}" for i in range(150)] + ["y" * 700]}]})
    assert len(d["groups"][0]["items"]) == 100
    d = ps.clean({"groups": [{"id": "a", "name": "A", "items": ["y" * 700]}]})
    assert len(d["groups"][0]["items"][0]) == 500


def test_cleaning_and_duplicates():
    d = ps.clean({"groups": [{"id": "a", "name": " A ", "items": ["  hi ", "", "   ", "hi", 5, None, "yo"]},
                             {"name": "", "items": "bad"}, "junk"]})
    assert d["groups"][0]["items"] == ["hi", "yo"] and d["groups"][0]["name"] == "A"
    assert len(d["groups"]) == 2 and d["groups"][1]["name"] and d["groups"][1]["items"] == []
    assert d["groups"][1]["id"] and d["groups"][1]["id"] != "a"


def test_duplicate_ids_get_fresh():
    d = ps.clean({"groups": [{"id": "a", "name": "1"}, {"id": "a", "name": "2"}]})
    assert d["groups"][0]["id"] != d["groups"][1]["id"]


def test_active_group():
    g = [{"id": "a", "name": "A", "items": []}, {"id": "b", "name": "B", "items": []}]
    assert ps.clean({"groups": g, "active": "b"})["active"] == "b"
    assert ps.clean({"groups": g, "active": "zzz"})["active"] == "a"
    assert ps.clean({"groups": g})["active"] == "a"


def test_import_txt_and_csv():
    d = ps.clean({"groups": [{"id": "a", "name": "A", "items": ["one"]}]})
    out = ps.import_text(d, "a", "﻿one\n\n two \nthree, with comma\n")
    assert out["groups"][0]["items"] == ["one", "two", "three, with comma"]
    out = ps.import_text(d, "a", "x1;y\nx2,y\n\"q, r\";z\nx3\ttab\n", csv=True)
    assert out["groups"][0]["items"] == ["one", "x1", "x2", "q, r", "x3"]
    out = ps.import_text(d, None, "act")           # None = активная
    assert out["groups"][0]["items"] == ["one", "act"]
    with pytest.raises(ValueError):
        ps.import_text(d, "nope", "x")


def test_export_roundtrip():
    d = ps.clean({"groups": [{"id": "a", "name": "A", "items": ["hi, there", "{a|b} c", "plain"]}]})
    blob = ps.export_csv(d, "a")
    assert blob.startswith(b"\xef\xbb\xbf")
    back = ps.import_text(ps.clean(None), None, blob.decode("utf-8"), csv=True)
    assert back["groups"][0]["items"] == ["hi, there", "{a|b} c", "plain"]
    with pytest.raises(ValueError):
        ps.export_csv(d, "nope")


def test_load_missing_and_broken(pfile):
    assert ps.load()["groups"][0]["name"] == "Общие"
    pfile.write_text("{not json", "utf-8")
    assert ps.load()["groups"][0]["name"] == "Общие"
    pfile.write_text("[1]", "utf-8")
    assert ps.load()["groups"][0]["name"] == "Общие"


def test_save_roundtrip(pfile):
    out = ps.save({"groups": [{"id": "a", "name": "A", "items": ["x", "x", "y"]}], "active": "a"})
    assert out["groups"][0]["items"] == ["x", "y"]
    assert json.loads(pfile.read_text("utf-8")) == out and ps.load() == out
    assert not list(pfile.parent.glob("*.tmp"))


def test_save_is_atomic(pfile, monkeypatch):
    ps.save({"groups": [{"id": "a", "name": "A", "items": ["old"]}]})

    def boom(*a, **k):
        raise OSError("disk")
    with monkeypatch.context() as m:
        m.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            ps.save({"groups": [{"id": "a", "name": "A", "items": ["new"]}]})
    assert ps.load()["groups"][0]["items"] == ["old"]


def test_api(pfile):
    assert api.get_phrases()["groups"][0]["name"] == "Общие"
    out = api.put_phrases({"groups": [{"id": "a", "name": "A", "items": ["x"]}], "active": "a"})
    assert out["groups"][0]["items"] == ["x"]
    with pytest.raises(HTTPException) as e:
        api.put_phrases([1])
    assert e.value.status_code == 400
    r = api.import_phrases({"group": "a", "text": "y\nx\nz"})
    assert r["added"] == 2 and r["groups"][0]["items"] == ["x", "y", "z"]
    assert ps.load()["groups"][0]["items"] == ["x", "y", "z"]
    r = api.import_phrases({"group": "a", "text": "p;q", "filename": "f.CSV"})
    assert "p" in r["groups"][0]["items"]
    with pytest.raises(HTTPException) as e:
        api.import_phrases({"group": "zz", "text": "y"})
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        api.import_phrases({"group": "a", "text": 5})
    assert e.value.status_code == 400
    resp = api.export_phrases(group="a")
    assert resp.media_type.startswith("text/csv") and resp.body.startswith(b"\xef\xbb\xbf")
    assert "attachment" in resp.headers["content-disposition"]
    with pytest.raises(HTTPException) as e:
        api.export_phrases(group="zz")
    assert e.value.status_code == 404


def test_backup_includes_phrases():
    assert "phrases.json" in backup.EXTRA_DATA
