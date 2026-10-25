"""Здоровье телефона: разбор /proc/meminfo, df, /proc/stat и тревоги реестра."""
from farm import config, health
from farm.devices.registry import Device

MEM = ("MemTotal:        3815884 kB\nMemFree:          123456 kB\n"
       "MemAvailable:    1907942 kB\n")
DF = ("Filesystem       Size  Used Avail Use% Mounted on\n"
      "/dev/block/dm-9  118G   60G   58G  51% /data\n")
STAT1 = "cpu  1000 0 500 8000 100 0 0 0 0 0\n"
STAT2 = "cpu  1300 0 700 8400 100 0 0 0 0 0\n"
OUT = f"{MEM}#df\n{DF}#stat\n{STAT1}"


def test_split_sections():
    got = health.split_sections(OUT)
    assert got["mem"].startswith("MemTotal") and "/data" in got["df"] and got["stat"].startswith("cpu")


def test_split_sections_missing_parts():
    got = health.split_sections(MEM)
    assert got["df"] == "" and got["stat"] == ""


def test_meminfo_and_free_percent():
    info = health.parse_meminfo(MEM)
    assert info == {"total_kb": 3815884, "available_kb": 1907942}
    assert health.ram_free_pct(info) == 50
    assert health.parse_meminfo("") is None
    assert health.ram_free_pct(None) is None


def test_meminfo_without_available_uses_free_plus_cache():
    text = "MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 50 kB\nCached: 150 kB\n"
    assert health.ram_free_pct(health.parse_meminfo(text)) == 30


def test_df_used_percent():
    assert health.parse_df(DF) == 51
    assert health.parse_df("") is None
    assert health.parse_df("/dev/x 1G 1G 0 100% /data\n") == 100


def test_cpu_stat_and_percent():
    prev, cur = health.parse_cpu_stat(STAT1), health.parse_cpu_stat(STAT2)
    assert prev == (1500, 9600) and cur == (2000, 10500)
    assert health.cpu_percent(prev, cur) == 56          # 500 занятых из 900
    assert health.cpu_percent(None, cur) is None
    assert health.cpu_percent(cur, cur) is None          # нулевой промежуток
    assert health.parse_cpu_stat("garbage") is None


def test_read_returns_metrics_and_next_sample():
    first, sample = health.read(OUT, None)
    assert first == {"ram_free": 50, "rom_used": 51, "cpu": None}
    out2 = f"{MEM}#df\n{DF}#stat\n{STAT2}"
    second, _ = health.read(out2, sample)
    assert second["cpu"] == 56


def _device(**kw):
    d = Device(serial="S1")
    d.state = "device"
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_warnings_for_full_storage_and_low_ram():
    d = _device(rom_used=95, ram_free=5)
    text = " | ".join(d.warnings())
    assert "память почти заполнена" in text and "95%" in text
    assert "мало оперативной памяти" in text


def test_no_warnings_when_healthy_or_unknown():
    assert _device(rom_used=60, ram_free=40).warnings() == []
    assert _device().warnings() == []


def test_thresholds_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "ROM_ALERT_PCT", 50)
    assert any("заполнена" in w for w in _device(rom_used=51).warnings())


def test_forget_health_clears_new_fields():
    d = _device(rom_used=80, ram_free=10, cpu=30)
    d.forget_health()
    assert d.rom_used is None and d.ram_free is None and d.cpu is None


def test_to_dict_exposes_new_fields():
    d = _device(rom_used=80, ram_free=10, cpu=30).to_dict()
    assert (d["rom_used"], d["ram_free"], d["cpu"]) == (80, 10, 30)
