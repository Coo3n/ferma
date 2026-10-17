"""Мелочи из AirDroid/Escrcpy: «Погасить экран» и выгрузка запусков в CSV."""
import csv
import io
import re

from farm.api import jobs as jobs_api
from farm.api import screen


def test_screen_off_in_actions_sends_sleep_key(monkeypatch):
    calls = []
    monkeypatch.setattr(screen.adb, "shell",
                        lambda serial, cmd, timeout=None: calls.append((serial, cmd)) or "")
    assert "screen_off" in screen.ACTIONS
    screen.ACTIONS["screen_off"]("S1", {"type": "screen_off"})
    assert calls == [("S1", "input keyevent 223")]


def test_bulk_uses_same_actions_table():
    from farm.api import bulk
    assert bulk.ACTIONS is screen.ACTIONS


FAKE = [
    {"scenario_name": "Лента VK", "scenario_key": "vk_feed", "device_name": "Телефон 1",
     "serial": "S1", "status": "passed", "created_at": 1_700_000_000.0,
     "started_at": 1_700_000_001.0, "duration": 12.34, "error": None},
    {"scenario_name": "", "scenario_key": "tg_read", "device_name": "",
     "serial": "S2", "status": "failed", "created_at": 1_700_000_100.0,
     "started_at": 1_700_000_101.0, "duration": 3.0, "error": "нет кнопки\n«Войти»; стоп"},
    {"scenario_name": "Х", "scenario_key": "x", "device_name": "Т3", "serial": "S3",
     "status": "queued", "created_at": 1_700_000_200.0, "started_at": None,
     "duration": 0, "error": None},
]


def _rows(body: bytes):
    assert body.startswith(b"\xef\xbb\xbf")          # BOM — Excel поймёт UTF-8
    text = body.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def test_export_csv(monkeypatch):
    seen = {}

    def fake_list(limit=60, serial=None, batch=None):
        seen["limit"] = limit
        return FAKE

    monkeypatch.setattr(jobs_api.runner, "list_jobs", fake_list)
    resp = jobs_api.export_csv()
    assert seen["limit"] > 10_000                     # весь журнал, не первая страница
    assert resp.media_type.startswith("text/csv")
    disp = resp.headers["content-disposition"]
    assert re.fullmatch(r'attachment; filename="farm-jobs-\d{4}-\d{2}-\d{2}\.csv"', disp)

    rows = _rows(resp.body)
    assert rows[0] == ["время начала", "сценарий", "телефон", "статус", "длительность (с)", "ошибка"]
    assert len(rows) == 4
    r1, r2, r3 = rows[1:]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", r1[0])
    assert r1[1:] == ["Лента VK", "Телефон 1", "прошёл", "12,3", ""]
    assert r2[1:4] == ["tg_read", "S2", "упал"]         # пустые имена → ключ и серийник
    assert r2[5] == "нет кнопки «Войти»; стоп"           # перевод строки схлопнут, «;» в кавычках
    assert r3[3:5] == ["в очереди", ""]                  # не начатая — без длительности


def test_export_route_before_job_id():
    paths = [r.path for r in jobs_api.router.routes]
    assert paths.index("/api/jobs/export.csv") < paths.index("/api/jobs/{job_id}")
