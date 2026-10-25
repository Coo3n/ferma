"""Резервная копия: что кладётся, что нет, безопасное восстановление."""
import asyncio
import io
import zipfile

import pytest
from fastapi import HTTPException

from farm import backup, config
from farm.api import backup as api_backup


@pytest.fixture
def farm(tmp_path, monkeypatch):
    data, sc, adb = tmp_path / "data", tmp_path / "scenarios", tmp_path / ".android"
    for d in (data, sc, adb):
        d.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "SCENARIOS_DIR", sc)
    monkeypatch.setattr(backup, "ADB_DIR", adb)
    (data / "accounts.json").write_text('{"a": 1}', "utf-8")
    (data / "groups.json").write_text('{"g": 1}', "utf-8")
    (data / "vlm.json").write_text('{"key": "SECRET"}', "utf-8")          # ключ нейросети в копию не идёт
    (data / "artifacts").mkdir()
    (data / "artifacts" / "big.jpg").write_bytes(b"x" * 100)
    (sc / "vk_like.py").write_text("RECORDED = True\n", "utf-8")
    (sc / "_template.py").write_text("x = 1\n", "utf-8")
    (sc / "vk_like_assets").mkdir()
    (sc / "vk_like_assets" / "recipe.json").write_text("{}", "utf-8")
    (adb / "adbkey").write_text("PRIVATE", "utf-8")
    (adb / "adbkey.pub").write_text("PUBLIC", "utf-8")
    return tmp_path


def names(blob):
    return sorted(zipfile.ZipFile(io.BytesIO(blob)).namelist())


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_build_includes_whitelisted_files_only(farm):
    got = names(backup.build())
    assert "data/accounts.json" in got and "data/groups.json" in got
    assert "scenarios/vk_like.py" in got and "scenarios/vk_like_assets/recipe.json" in got
    assert not any("vlm" in n or "artifacts" in n or "_template" in n for n in got)
    assert not any(n.startswith("adb/") for n in got)


def test_adb_key_only_when_asked(farm):
    assert "adb/adbkey" in names(backup.build(include_adb_key=True))


def test_inspect_lists_files_and_key_flag(farm):
    info = backup.inspect(backup.build(include_adb_key=True))
    assert info["has_adb_key"] is True and "data/accounts.json" in info["files"]
    assert backup.inspect(backup.build())["has_adb_key"] is False


def test_inspect_rejects_non_zip():
    with pytest.raises(ValueError):
        backup.inspect(b"not a zip")


def test_restore_round_trip_and_previous_saved(farm):
    blob = backup.build()
    (config.DATA_DIR / "accounts.json").write_text('{"changed": true}', "utf-8")
    report = backup.restore(blob)
    assert (config.DATA_DIR / "accounts.json").read_text("utf-8") == '{"a": 1}'
    assert "data/accounts.json" in report["restored"]
    saved = report["saved_previous_to"]
    assert saved and (config.DATA_DIR / ".restore-backup").exists()
    assert any(p.read_text("utf-8") == '{"changed": true}'
               for p in (config.DATA_DIR / ".restore-backup").rglob("accounts.json"))


@pytest.mark.parametrize("name", [
    "../evil.txt", "data/../evil.txt", "/etc/passwd", "data/vlm.json", "data/artifacts/x.jpg",
    "scenarios/../x.py", "scenarios/x.sh", "scenarios/a/b.py", "adb/other", "random.txt",
    "data\\accounts.json", "scenarios/gallery/tiktok_feed.py",
])
def test_restore_skips_unsafe_or_unknown_names(farm, name):
    report = backup.restore(make_zip({name: "x"}))
    assert report["restored"] == []
    assert report["skipped"][0]["name"] == name
    assert not (farm / "evil.txt").exists()


def test_restore_adb_key_only_when_allowed(farm):
    blob = make_zip({"adb/adbkey": "NEWKEY"})
    assert backup.restore(blob, adb_key=False)["restored"] == []
    assert (backup.ADB_DIR / "adbkey").read_text("utf-8") == "PRIVATE"
    assert backup.restore(blob, adb_key=True)["restored"] == ["adb/adbkey"]
    assert (backup.ADB_DIR / "adbkey").read_text("utf-8") == "NEWKEY"


def test_restore_enforces_total_size(farm, monkeypatch):
    monkeypatch.setattr(backup, "MAX_TOTAL", 10)
    with pytest.raises(ValueError):
        backup.restore(make_zip({"data/accounts.json": "x" * 50}))


def test_restore_enforces_file_count(farm, monkeypatch):
    monkeypatch.setattr(backup, "MAX_FILES", 2)
    with pytest.raises(ValueError):
        backup.restore(make_zip({f"data/accounts{i}.json": "x" for i in range(5)}))


class Req:
    def __init__(self, data):
        self.headers = {"content-length": str(len(data))}
        self._data = data

    async def stream(self):
        yield self._data


def test_api_export_returns_zip_response(farm):
    resp = api_backup.export_backup({"adb_key": False})
    assert resp.media_type == "application/zip"
    assert "farm-backup-" in resp.headers["content-disposition"]
    assert "data/accounts.json" in names(resp.body)


def test_api_inspect_and_restore(farm):
    blob = backup.build()
    info = asyncio.run(api_backup.inspect_backup(Req(blob)))
    assert "data/accounts.json" in info["files"]
    out = asyncio.run(api_backup.restore_backup(Req(blob), adb_key=0))
    assert "data/accounts.json" in out["restored"]


def test_api_rejects_bad_archive_with_400(farm):
    with pytest.raises(HTTPException) as e:
        asyncio.run(api_backup.inspect_backup(Req(b"junk")))
    assert e.value.status_code == 400
