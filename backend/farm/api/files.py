"""Файлы на телефоне: посмотреть, скачать, загрузить, удалить.

Работаем только внутри общего хранилища (/sdcard): системные разделы и данные
чужих приложений отсюда недоступны, и это сознательное ограничение, а не
недоделка — оператор не должен случайно снести систему одним кликом.
Каждый путь от браузера проходит через `clean_path`: он единственный решает,
что пускать в `adb shell`.
"""
from __future__ import annotations

import io
import posixpath
import re
import shlex
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from .. import adb
from .bulk import _discard, _upload, safe_name
from .screen import _require_online

router = APIRouter(prefix="/api/devices")

ROOT = "/sdcard"
ROOT_ALIASES = ("/storage/emulated/0", "/storage/self/primary", "/sdcard")
SHELL_TIMEOUT = 30
PULL_TIMEOUT = 900
LIST_LIMIT = 5000
PREVIEW_MAX_BYTES = 30 * 1024 * 1024
PREVIEW_WIDTH = 640
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

# Где у телефонов лежат привычные места. Берём первое существующее: на
# Samsung скриншоты в DCIM, на Pixel — в Pictures.
PLACES = (
    ("camera", ("/sdcard/DCIM/Camera", "/sdcard/DCIM")),
    ("screenshots", ("/sdcard/Pictures/Screenshots", "/sdcard/DCIM/Screenshots",
                     "/sdcard/Screenshots")),
    ("downloads", ("/sdcard/Download",)),
    ("pictures", ("/sdcard/Pictures",)),
    ("movies", ("/sdcard/Movies",)),
)


def clean_path(path: str | None) -> str:
    """Путь на телефоне → нормальный абсолютный путь внутри /sdcard.

    ValueError — путь не пускаем. `..` отвергаем до нормализации, а не
    «схлопываем»: «/sdcard/../data» не должен молча стать чем-то другим.
    """
    raw = str(path if path is not None else "").strip()
    if not raw:
        return ROOT
    if "\x00" in raw or "\n" in raw or "\r" in raw:
        raise ValueError("недопустимый путь")
    raw = raw.replace("\\", "/")
    if ".." in raw.split("/"):
        raise ValueError("недопустимый путь")
    if not raw.startswith("/"):
        raw = f"{ROOT}/{raw}"
    for alias in ROOT_ALIASES:
        if raw == alias or raw.startswith(alias + "/"):
            raw = ROOT + raw[len(alias):]
            break
    else:
        raise ValueError("доступно только хранилище телефона")
    return posixpath.normpath(raw)


def _path(value: str | None) -> str:
    try:
        return clean_path(value)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _q(path: str) -> str:
    return shlex.quote(path)


def _parent(path: str) -> str | None:
    return None if path == ROOT else posixpath.dirname(path)


# toybox: «drwxrwx--x 4 u0_a1 media_rw 3452 2024-05-01 10:22 DCIM»;
# старый toolbox — без числа ссылок. Что не разобралось, пропускаем.
_LS_LINE = re.compile(
    r"^(?P<mode>[-dlcbps][-rwxsStT]{9})[.+]?\s+(?:\d+\s+)?\S+\s+\S+\s+"
    r"(?:\d+,\s*)?(?P<size>\d+)\s+(?P<date>\d{4}-\d\d-\d\d)\s+(?P<time>\d\d:\d\d)(?::\d\d)?"
    r"(?:\.\d+)?(?:\s+[+-]\d{4})?\s+(?P<name>.+)$")


def parse_ls(output: str, folder: str) -> list[dict]:
    items = []
    for line in output.splitlines():
        m = _LS_LINE.match(line.rstrip())
        if not m:
            continue
        name = m["name"]
        if m["mode"][0] == "l":
            name = name.split(" -> ", 1)[0]
        if name in (".", "..") or "/" in name:
            continue
        is_dir = m["mode"][0] == "d"
        items.append({
            "name": name,
            "dir": is_dir,
            "link": m["mode"][0] == "l",
            "size": int(m["size"]),
            "mtime": f"{m['date']} {m['time']}",
            "path": posixpath.join(folder, name),
        })
    return items


@router.get("/{serial}/fs/places")
def places(serial: str):
    """Привычные места, которые на этом телефоне правда есть."""
    _require_online(serial)
    script = "; ".join(f'[ -d {p} ] && echo {p}' for _, paths in PLACES for p in paths)
    try:
        out = adb.shell(serial, script, timeout=SHELL_TIMEOUT)
    except adb.AdbError as e:
        raise HTTPException(500, f"не удалось заглянуть в телефон: {e}")
    present = {line.strip() for line in out.splitlines()}
    found = []
    for key, paths in PLACES:
        path = next((p for p in paths if p in present), None)
        if path:
            found.append({"id": key, "path": path})
    return {"root": ROOT, "places": found}


@router.get("/{serial}/fs")
def listing(serial: str, path: str = Query(ROOT)):
    _require_online(serial)
    folder = _path(path)
    try:
        out = adb.shell(serial, ["ls", "-lA", _q(folder) + "/"], timeout=SHELL_TIMEOUT)
    except adb.AdbError as e:
        text = str(e)
        if "No such file" in text:
            raise HTTPException(404, "такой папки на телефоне нет")
        if "Permission denied" in text:
            raise HTTPException(403, "телефон не пускает в эту папку")
        raise HTTPException(500, f"не удалось открыть папку: {text[-200:]}")
    items = parse_ls(out, folder)
    items.sort(key=lambda i: (not i["dir"], i["name"].lower()))
    total = len(items)
    return {"path": folder, "parent": _parent(folder), "items": items[:LIST_LIMIT],
            "total": total, "truncated": total > LIST_LIMIT}


def _pull(serial: str, path: str, into: Path) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    try:
        adb.raw(["pull", path, str(into) + "/"], serial=serial, timeout=PULL_TIMEOUT)
    except adb.AdbError as e:
        raise HTTPException(500, f"не удалось забрать файл: {str(e)[-200:]}")
    got = into / posixpath.basename(path)
    if not got.exists():
        raise HTTPException(404, "файла на телефоне нет")
    return got


def _zip_dir_name(path: str) -> str:
    return safe_name(posixpath.basename(path) or "phone") + ".zip"


@router.get("/{serial}/fs/download")
def download(serial: str, path: list[str] = Query(...)):
    """Один файл — как есть; папка или несколько — одним zip."""
    device = _require_online(serial)
    paths = list(dict.fromkeys(_path(p) for p in path))
    if not paths or ROOT in paths:
        raise HTTPException(400, "выберите файлы или папки, а не всё хранилище")
    tmp = Path(tempfile.mkdtemp(prefix="farm-fs-"))
    cleanup = BackgroundTask(shutil.rmtree, tmp, True)
    try:
        pulled = [_pull(serial, p, tmp / str(i)) for i, p in enumerate(paths)]
        if len(pulled) == 1 and pulled[0].is_file():
            return FileResponse(pulled[0], filename=pulled[0].name, background=cleanup)
        zip_name = (_zip_dir_name(paths[0]) if len(paths) == 1 else
                    f"{safe_name(device.name)}_{time.strftime('%Y%m%d_%H%M%S')}.zip")
        archive = tmp / "out.zip"
        used: set[str] = set()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
            for src in pulled:
                top = src.name
                n = 1
                while top in used:
                    n += 1
                    top = f"{src.stem} ({n}){src.suffix}"
                used.add(top)
                if src.is_file():
                    zf.write(src, top)
                    continue
                for f in src.rglob("*"):
                    if f.is_file():
                        zf.write(f, f"{top}/{f.relative_to(src).as_posix()}")
        return FileResponse(archive, filename=zip_name, media_type="application/zip",
                            background=cleanup)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


@router.get("/{serial}/fs/preview")
def preview(serial: str, path: str = Query(...)):
    """Уменьшенная картинка для просмотра, чтобы не качать гигабайты."""
    _require_online(serial)
    file = _path(path)
    if not file.lower().endswith(IMAGE_EXT):
        raise HTTPException(415, "посмотреть можно только картинку")
    try:
        data = adb.exec_out(serial, ["cat", _q(file)], timeout=SHELL_TIMEOUT * 2)
    except adb.AdbError as e:
        raise HTTPException(500, f"не удалось открыть картинку: {str(e)[-200:]}")
    if len(data) > PREVIEW_MAX_BYTES:
        raise HTTPException(413, "картинка слишком большая для просмотра — скачайте её")
    from PIL import Image, ImageOps

    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception:  # noqa: BLE001
        raise HTTPException(415, "эту картинку не получилось показать")
    image.thumbnail((PREVIEW_WIDTH, PREVIEW_WIDTH * 2))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return Response(buffer.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=300"})


def _scan(serial: str, path: str) -> None:
    """Галерея узнаёт о новом (или пропавшем) файле, не дожидаясь перезагрузки."""
    try:
        adb.shell(serial, ["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                           "-d", _q(f"file://{path}")], timeout=SHELL_TIMEOUT)
    except adb.AdbError:
        pass


def _free_name(serial: str, folder: str, name: str) -> str:
    """«photo.jpg» занят → «photo (2).jpg»: чужой файл молча не затираем."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    else:
        ext = "." + ext
    try:
        out = adb.shell(serial, ["ls", "-1A", _q(folder) + "/"], timeout=SHELL_TIMEOUT)
    except adb.AdbError:
        return name
    taken = {line.strip() for line in out.splitlines()}
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = f"{stem} ({n}){ext}"
    return candidate


@router.post("/{serial}/fs/upload")
async def upload(serial: str, request: Request, path: str = Query(ROOT), name: str = Query(...)):
    _require_online(serial)
    folder = _path(path)
    src = await _upload(request, name)
    try:
        target = _free_name(serial, folder, src.name)
        dest = posixpath.join(folder, target)
        try:
            adb.raw(["push", str(src), dest], serial=serial, timeout=PULL_TIMEOUT)
        except adb.AdbError as e:
            text = str(e)
            if "No space" in text or "ENOSPC" in text:
                raise HTTPException(507, "на телефоне не хватает места")
            raise HTTPException(500, f"файл не загрузился: {text[-200:]}")
        _scan(serial, dest)
        return {"ok": True, "path": dest, "name": target}
    finally:
        _discard(src)


@router.post("/{serial}/fs/mkdir")
def mkdir(serial: str, payload: dict = Body(...)):
    _require_online(serial)
    folder = _path(payload.get("path"))
    if folder == ROOT:
        raise HTTPException(400, "укажите имя папки")
    try:
        adb.shell(serial, ["mkdir", "-p", _q(folder)], timeout=SHELL_TIMEOUT)
    except adb.AdbError as e:
        raise HTTPException(500, f"папку не создать: {str(e)[-200:]}")
    return {"ok": True, "path": folder}


@router.post("/{serial}/fs/delete")
def delete(serial: str, payload: dict = Body(...)):
    """Удалить выбранное. Само хранилище и его верхние папки (DCIM, Android…) не трогаем."""
    _require_online(serial)
    raw = payload.get("paths")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "не выбрано ни одного файла")
    paths = list(dict.fromkeys(_path(p) for p in raw))
    for p in paths:
        if posixpath.dirname(p) == ROOT or p == ROOT:
            raise HTTPException(400, "верхние папки хранилища удалять нельзя")
    done, failed = 0, []
    for p in paths:
        try:
            adb.shell(serial, ["rm", "-rf", _q(p)], timeout=SHELL_TIMEOUT * 4)
            _scan(serial, p)
            done += 1
        except adb.AdbError as e:
            failed.append({"path": p, "error": str(e)[-120:]})
    return {"ok": not failed, "deleted": done, "failed": failed}
