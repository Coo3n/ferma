"""Резервная копия фермы: архив с данными, записанными сценариями и (по желанию) ключом adb.

Зачем. Сломался компьютер — и сорок телефонов надо авторизовать заново, а
аккаунты, группы и расписание вводить с нуля. С копией ферма встаёт на новом
компьютере за минуту. Ключ adb кладётся ТОЛЬКО по явной галке: с ним любой
получает доступ ко всем телефонам.

Восстановление не доверяет архиву: имена в нём не превращаются в пути, а
сверяются с белым списком (zip-slip невозможен — путь строим сами), размер и
число файлов ограничены, а текущие файлы перед заменой уезжают в
data/.restore-backup/.
"""
from __future__ import annotations

import io
import os
import re
import time
import zipfile
from pathlib import Path

from . import config

ADB_DIR = Path.home() / ".android"
ADB_KEYS = ("adbkey", "adbkey.pub")
EXTRA_DATA = ("apks.json", "budget.json")
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 2000
_PY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*\.py$")
_ASSET_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*_assets$")
_ASSET_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def _data_names():
    return tuple(config.DATA_FILES) + EXTRA_DATA


def _target(name: str):
    """Куда писать файл из архива или None, если имя не наше. Путь строится
    из проверенных кусков, а не берётся из архива."""
    if "\\" in name or name.startswith("/") or ".." in name.split("/"):
        return None
    parts = name.split("/")
    if parts[0] == "data" and len(parts) == 2 and parts[1] in _data_names():
        return Path(config.DATA_DIR) / parts[1]
    if parts[0] == "scenarios":
        if len(parts) == 2 and _PY.match(parts[1]) and not parts[1].startswith("_"):
            return Path(config.SCENARIOS_DIR) / parts[1]
        if len(parts) == 3 and _ASSET_DIR.match(parts[1]) and _ASSET_FILE.match(parts[2]):
            return Path(config.SCENARIOS_DIR) / parts[1] / parts[2]
    if parts[0] == "adb" and len(parts) == 2 and parts[1] in ADB_KEYS:
        return Path(ADB_DIR) / parts[1]
    return None


def build(include_adb_key: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in _data_names():
            path = Path(config.DATA_DIR) / name
            if path.is_file():
                z.write(path, f"data/{name}")
        sc = Path(config.SCENARIOS_DIR)
        for path in sorted(sc.glob("*.py")):
            if not path.name.startswith("_"):
                z.write(path, f"scenarios/{path.name}")
        for folder in sorted(sc.glob("*_assets")):
            if folder.is_dir():
                for path in sorted(folder.iterdir()):
                    if path.is_file():
                        z.write(path, f"scenarios/{folder.name}/{path.name}")
        if include_adb_key:
            for name in ADB_KEYS:
                path = Path(ADB_DIR) / name
                if path.is_file():
                    z.write(path, f"adb/{name}")
    return buf.getvalue()


def _open(blob: bytes) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise ValueError("это не архив резервной копии фермы")
    infos = z.infolist()
    if len(infos) > MAX_FILES:
        raise ValueError(f"в архиве слишком много файлов ({len(infos)})")
    if sum(i.file_size for i in infos) > MAX_TOTAL:
        raise ValueError("архив слишком большой после распаковки")
    return z


def inspect(blob: bytes) -> dict:
    z = _open(blob)
    files = [i.filename for i in z.infolist() if not i.is_dir()]
    return {"files": files, "has_adb_key": any(f.startswith("adb/") for f in files),
            "bytes": len(blob)}


def restore(blob: bytes, adb_key: bool = False) -> dict:
    z = _open(blob)
    restored, skipped = [], []
    saved_root = Path(config.DATA_DIR) / ".restore-backup" / time.strftime("%Y%m%d-%H%M%S")
    saved_any = False
    for info in z.infolist():
        if info.is_dir():
            continue
        name = info.filename
        target = _target(name)
        if target is None:
            skipped.append({"name": name, "why": "имя не входит в состав копии"})
            continue
        if name.startswith("adb/") and not adb_key:
            skipped.append({"name": name, "why": "ключ adb не разрешён галкой"})
            continue
        data = z.read(info)
        if target.exists():
            keep = saved_root / name
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(target.read_bytes())
            saved_any = True
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        if name.startswith("adb/") and name.endswith("adbkey"):
            os.chmod(tmp, 0o600)          # приватный ключ не должен читаться чужими
        os.replace(tmp, target)
        restored.append(name)
    return {"restored": restored, "skipped": skipped,
            "saved_previous_to": str(saved_root) if saved_any else None}
