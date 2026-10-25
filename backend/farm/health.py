"""Здоровье телефона: память, место и загрузка процессора.

Чистый разбор вывода adb, без самого adb. Всё читается ОДНОЙ командой за
проход опроса: сорок телефонов раз в 20 секунд не должны получать по четыре
вызова. Загрузка CPU считается между двумя проходами (по /proc/stat), поэтому
ждать полсекунды на телефоне не нужно.
"""
from __future__ import annotations

import re

HEALTH_CMD = "head -n 5 /proc/meminfo; echo '#df'; df /data; echo '#stat'; head -n 1 /proc/stat"

_MEM = re.compile(r"^(\w+):\s+(\d+)\s*kB", re.M)
_PCT = re.compile(r"(\d{1,3})%")


def split_sections(out) -> dict:
    """Вывод HEALTH_CMD на три части; чего нет — пустая строка."""
    text = out or ""
    mem, _, rest = text.partition("#df")
    df, _, stat = rest.partition("#stat")
    return {"mem": mem.strip(), "df": df.strip(), "stat": stat.strip()}


def parse_meminfo(text):
    fields = {k: int(v) for k, v in _MEM.findall(text or "")}
    if not fields.get("MemTotal"):
        return None
    available = fields.get("MemAvailable")
    if available is None:                     # старые Android: свободно + буферы + кэш
        available = fields.get("MemFree", 0) + fields.get("Buffers", 0) + fields.get("Cached", 0)
    return {"total_kb": fields["MemTotal"], "available_kb": available}


def ram_free_pct(info):
    if not info or not info["total_kb"]:
        return None
    return int(round(100 * info["available_kb"] / info["total_kb"]))


def parse_df(text):
    """Процент занятого места на /data из вывода df."""
    for line in reversed((text or "").splitlines()):
        match = _PCT.search(line)
        if match:
            return int(match.group(1))
    return None


def parse_cpu_stat(text):
    """(занято, всего) из строки «cpu  user nice system idle iowait …»."""
    parts = (text or "").split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    try:
        nums = [int(p) for p in parts[1:]]
    except ValueError:
        return None
    total = sum(nums[:8])
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    return total - idle, total


def cpu_percent(prev, cur):
    """Загрузка между двумя образцами; нет прошлого или нулевой промежуток — None."""
    if not prev or not cur or cur[1] <= prev[1]:
        return None
    return int(round(100 * (cur[0] - prev[0]) / (cur[1] - prev[1])))


def read(out, prev):
    """Метрики из вывода HEALTH_CMD и новый образец CPU для следующего прохода."""
    parts = split_sections(out)
    sample = parse_cpu_stat(parts["stat"])
    metrics = {"ram_free": ram_free_pct(parse_meminfo(parts["mem"])),
               "rom_used": parse_df(parts["df"]),
               "cpu": cpu_percent(prev, sample)}
    return metrics, sample
