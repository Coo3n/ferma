# Проверки телефона и библиотека APK — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** сценарий умеет проверять системное состояние телефона (приложение и его версия, заряд, интернет, место, аккаунт) и сам ставить нужное приложение из библиотеки APK на ферме.

**Architecture:** APK хранятся на ферме (`data/apks/<пакет>.apk` + индекс `data/apks.json`), пакет и версия читаются из бинарного манифеста чистым Python. В схеме шагов два новых вида: блок `if_phone` (как `if_seen`, но условие — факт о телефоне) и шаг `ensure_app`. Codegen превращает их в `if ctx.phone_is(...)` и `ctx.ensure_app(...)`; факты собирает `farm/control/facts.py` через adb. Фронт: вкладка «Приложения» в «Сценариях», группа «Если на телефоне» в «Добавить шаг», готовое действие «Приложение готово».

**Tech Stack:** Python 3.11, FastAPI, pytest; ванильный JS (обычные скрипты, без модулей), node для JS-тестов.

**Спека:** `docs/superpowers/specs/2026-10-19-phone-checks-design.md`.

## Global Constraints

- Новых Python-зависимостей нет: ферма работает офлайн и на Windows, `aapt` нет.
- Тесты: `cd backend && ../.venv/bin/python -m pytest -q`. TestClient недоступен — роутеры зовём как функции.
- Видимые слова: «телефон» (не «устройство»), «приложение» (не «пакет»), «запуск». `package` — только в `title`.
- Весь новый видимый текст во фронте — через `t('раздел.ключ')` с литеральным ключом, строки в `frontend/strings/ru.json`; ключ по правилу `[a-z]+\.[a-z0-9_]+`; неиспользуемых строк быть не должно (`test_strings.py`).
- CSS: только токены (`--fs-1..5`, `--r1..3`, цвета из `frontend/design/tokens.css`), без сырых hex и px-шрифтов, без uppercase-подписей.
- Диалоги: `mTitle`/`mBody`/`mActs` + `openModal()`; разрушительное — `armConfirm(btn, text)`; выключенная кнопка — `disableWithReason`.
- Не больше 4 одновременных установок APK на ферму (40 × 100 МБ по USB кладут хаб).
- Версия сравнивается по числовым частям («8.40.1» → (8, 40, 1)); нечитаемая версия — ошибка «не понять версию», не догадка.
- Ошибка adb при чтении факта: один повтор, затем `StepFailed` «не удалось узнать …». Ложное «нет» не возвращаем.
- Приложение с другой подписью сами не удаляем.
- Коммиты — по-русски, как в истории репозитория, с подписью `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Отступления от спеки (решено при планировании, внести в спеку в Task 11):**
1. Отдельного `POST /api/devices/{serial}/phone-check` нет: ▶ на блоке идёт обычным `recRunStep`, ответ — строка журнала «на телефоне: …». Тот же путь, что у ▶ на `if_seen`.
2. Группа «Если на экране» не переименовывается: рядом новая группа «Если на телефоне» (ключ `phone`) — семь карточек в одной группе с тремя экранными читались бы стеной.
3. Запасного сравнения по `version_code` нет — нечитаемая версия даёт понятную ошибку.
4. Интернет проверяется `ping` с телефона (8.8.8.8, затем 77.88.8.8); «сторож сети» фермы следит за adb по Wi-Fi, а не за интернетом.
5. Коды причин установки уже есть в `bulk.py` (`signature`, `old_android`, `no_space`, …) — новые не нужны.
6. Шаг B добавляется как готовое действие (`presets.py`, ключ `ensure_app`) в группе «Действие».

---

## Файлы

| Файл | Что делает |
|---|---|
| `backend/farm/apkinfo.py` (новый) | Разбор бинарного `AndroidManifest.xml`: пакет, versionCode, versionName, minSdk |
| `backend/farm/apklib.py` (новый) | Библиотека APK: индекс, добавить/заменить/переименовать/удалить, установка под семафором, счётчик использования |
| `backend/farm/api/apks.py` (новый) | REST `/api/apks` |
| `backend/farm/control/facts.py` (новый) | Факты о телефоне: версия приложения, свободное место, интернет, заряд; сравнение версий |
| `backend/farm/context.py` | `ctx.phone_is`, `ctx.ensure_app` |
| `backend/farm/recorder/steps.py` | Виды `if_phone`, `ensure_app`, проверки, подписи, схема |
| `backend/farm/recorder/codegen.py` | Генерация кода новых шагов |
| `backend/farm/recorder/validate.py` + `api/recorder.py` | Предупреждение «нет в библиотеке» |
| `backend/farm/recorder/presets.py` | Готовое действие «Приложение готово» |
| `backend/tests/_axml.py` (новый) | Генератор маленьких APK для тестов |
| `frontend/js/apklib.js`, `frontend/css/apklib.css` (новые) | Вкладка «Приложения» |
| `frontend/js/blocks.js`, `addstep.js`, `recorder.js`, `apppick.js`, `steptools.js`, `app.js` | Блок `if_phone`, шаг `ensure_app`, выбор приложения из библиотеки |
| `frontend/index.html`, `frontend/strings/ru.json`, `frontend/css/recorder.css` | Разметка, строки, цвета блока |

---

### Task 1: Разбор APK (`apkinfo`)

**Files:**
- Create: `backend/farm/apkinfo.py`
- Create: `backend/tests/_axml.py`
- Test: `backend/tests/test_apkinfo.py`

**Interfaces:**
- Produces: `apkinfo.read(path) -> {"package": str, "version_code": int, "version_name": str, "min_sdk": int}`; `apkinfo.parse_manifest(data: bytes) -> dict` (те же ключи); `apkinfo.ApkError(ValueError)` с текстом для человека.
- Produces (тесты): `_axml.manifest(package, version_code, version_name, min_sdk=21, utf8=False, bare_names=False) -> bytes`; `_axml.apk(path, **kw) -> Path`.

- [ ] **Step 1: Генератор тестовых APK**

`backend/tests/_axml.py`:

```python
"""Маленькие APK для тестов: zip с бинарным AndroidManifest.xml.

Пишется ровно то, что читает farm/apkinfo.py: пул строк, карта ресурсов,
начало <manifest> и <uses-sdk>. bare_names=True — имена атрибутов в пуле
пустые, как в упакованных R8/aapt2 APK: остаются только id ресурсов.
"""
import struct
import zipfile
from pathlib import Path

NO = 0xFFFFFFFF
# Порядок важен: первые три строки — имена атрибутов, их id в карте ресурсов.
_IDS = [0x0101021B, 0x0101021C, 0x0101020C]


def _pool(strings, utf8):
    data, offsets = b"", []
    for s in strings:
        offsets.append(len(data))
        if utf8:
            raw = s.encode("utf-8")
            data += bytes([len(s), len(raw)]) + raw + b"\0"
        else:
            data += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0"
    while len(data) % 4:
        data += b"\0"
    header = 28
    body = struct.pack(f"<{len(strings)}I", *offsets) + data
    return struct.pack("<HHIIIIII", 0x0001, header, header + len(body), len(strings), 0,
                       0x100 if utf8 else 0, header + 4 * len(strings), 0) + body


def _resmap():
    body = struct.pack(f"<{len(_IDS)}I", *_IDS)
    return struct.pack("<HHI", 0x0180, 8, 8 + len(body)) + body


def _attr(name, *, string=None, number=None):
    if string is not None:
        return struct.pack("<IIIHBBI", NO, name, string, 8, 0, 0x03, string)
    return struct.pack("<IIIHBBI", NO, name, NO, 8, 0, 0x10, number)


def _start(tag, attrs):
    ext = struct.pack("<IIHHHHHH", NO, tag, 20, 20, len(attrs), 0, 0, 0)
    body = ext + b"".join(attrs)
    return struct.pack("<HHIII", 0x0102, 16, 16 + len(body), 1, NO) + body


def manifest(package, version_code, version_name, min_sdk=21, utf8=False, bare_names=False):
    names = ["", "", ""] if bare_names else ["versionCode", "versionName", "minSdkVersion"]
    strings = names + ["package", "manifest", "uses-sdk", package, version_name]
    body = (_pool(strings, utf8) + _resmap()
            + _start(4, [_attr(3, string=6), _attr(0, number=version_code),
                         _attr(1, string=7)])
            + _start(5, [_attr(2, number=min_sdk)]))
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def apk(path, **kw) -> Path:
    path = Path(path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", manifest(**kw))
        z.writestr("classes.dex", b"dex\n035\0")
    return path
```

- [ ] **Step 2: Падающие тесты**

`backend/tests/test_apkinfo.py`:

```python
"""Пакет и версия из APK без aapt."""
import zipfile

import pytest

import _axml
from farm import apkinfo

KW = dict(package="com.vkontakte.android", version_code=24015, version_name="8.40.1", min_sdk=26)


@pytest.mark.parametrize("utf8", [False, True])
@pytest.mark.parametrize("bare", [False, True])
def test_читает_пакет_и_версии(tmp_path, utf8, bare):
    path = _axml.apk(tmp_path / "vk.apk", utf8=utf8, bare_names=bare, **KW)
    assert apkinfo.read(path) == {"package": "com.vkontakte.android", "version_code": 24015,
                                  "version_name": "8.40.1", "min_sdk": 26}


def test_не_архив(tmp_path):
    path = tmp_path / "x.apk"
    path.write_bytes(b"hello")
    with pytest.raises(apkinfo.ApkError, match="не архив"):
        apkinfo.read(path)


def test_архив_без_манифеста(tmp_path):
    path = tmp_path / "x.apk"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(apkinfo.ApkError, match="AndroidManifest"):
        apkinfo.read(path)


def test_битый_манифест(tmp_path):
    path = tmp_path / "x.apk"
    data = _axml.manifest(**KW)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", data[:40])
    with pytest.raises(apkinfo.ApkError):
        apkinfo.read(path)


def test_текстовый_манифест_не_принимаем():
    with pytest.raises(apkinfo.ApkError, match="двоичном"):
        apkinfo.parse_manifest(b"<manifest package='a.b'/>")
```

- [ ] **Step 3: Убедиться, что падают**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_apkinfo.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'farm.apkinfo'`.

- [ ] **Step 4: Реализация**

`backend/farm/apkinfo.py`:

```python
"""Пакет и версия из APK без aapt: разбор бинарного AndroidManifest.xml.

Ферма работает офлайн и на Windows — тянуть build-tools ради трёх полей
незачем. Читаем только то, что нужно библиотеке APK: package, versionCode,
versionName, minSdkVersion.
"""
from __future__ import annotations

import struct
import zipfile

RES_STRING_POOL = 0x0001
RES_XML = 0x0003
RES_XML_START_ELEMENT = 0x0102
RES_XML_RESOURCE_MAP = 0x0180
UTF8_FLAG = 0x100
NO_INDEX = 0xFFFFFFFF
TYPE_STRING = 0x03
# В упакованных APK имена атрибутов в пуле часто пустые — остаётся id ресурса.
ATTR_IDS = {0x0101021B: "versionCode", 0x0101021C: "versionName",
            0x0101020C: "minSdkVersion"}


class ApkError(ValueError):
    """Файл не читается как APK; текст — для человека."""


def read(path) -> dict:
    """{package, version_code, version_name, min_sdk} из файла APK."""
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("AndroidManifest.xml")
    except zipfile.BadZipFile:
        raise ApkError("это не APK: файл не архив") from None
    except KeyError:
        raise ApkError("это не APK: внутри нет AndroidManifest.xml") from None
    except OSError as e:
        raise ApkError(f"файл не читается: {e}") from None
    try:
        info = parse_manifest(data)
    except (struct.error, IndexError, ValueError) as e:
        if isinstance(e, ApkError):
            raise
        raise ApkError("манифест APK повреждён") from None
    if not info["package"]:
        raise ApkError("в APK не указано приложение (package)")
    return info


def parse_manifest(data: bytes) -> dict:
    kind, header, total = struct.unpack_from("<HHI", data, 0)
    if kind != RES_XML:
        raise ApkError("манифест APK не в двоичном виде")
    out = {"package": "", "version_code": 0, "version_name": "", "min_sdk": 0}
    strings: list[str] = []
    resmap: list[int] = []
    at, end = header, min(total, len(data))
    while at + 8 <= end:
        kind, head, size = struct.unpack_from("<HHI", data, at)
        if size < 8 or at + size > end:
            raise ApkError("манифест APK повреждён")
        if kind == RES_STRING_POOL:
            strings = _strings(data, at)
        elif kind == RES_XML_RESOURCE_MAP:
            n = (size - head) // 4
            resmap = list(struct.unpack_from(f"<{n}I", data, at + head))
        elif kind == RES_XML_START_ELEMENT:
            _element(data, at + head, strings, resmap, out)
        at += size
    return out


def _strings(data: bytes, at: int) -> list[str]:
    _, head, _size, count, _styles, flags, start, _ = struct.unpack_from("<HHIIIIII", data, at)
    offsets = struct.unpack_from(f"<{count}I", data, at + head)
    base = at + start
    out = []
    for off in offsets:
        p = base + off
        if flags & UTF8_FLAG:
            p += 2 if data[p] & 0x80 else 1          # длина в символах — пропускаем
            n = data[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p + 1]
                p += 2
            else:
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                p += 2
            out.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
    return out


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _element(data: bytes, p: int, strings: list, resmap: list, out: dict) -> None:
    _ns, name, attr_start, attr_size, count = struct.unpack_from("<IIHHH", data, p)
    tag = strings[name] if name < len(strings) else ""
    if tag not in ("manifest", "uses-sdk"):
        return
    for i in range(count):
        a = p + attr_start + i * attr_size
        _ans, aname, raw, _vsize, _res0, vtype, vdata = struct.unpack_from("<IIIHBBI", data, a)
        key = strings[aname] if aname < len(strings) else ""
        if aname < len(resmap) and resmap[aname] in ATTR_IDS:
            key = ATTR_IDS[resmap[aname]]
        if raw != NO_INDEX and raw < len(strings):
            value = strings[raw]
        elif vtype == TYPE_STRING and vdata < len(strings):
            value = strings[vdata]
        else:
            value = vdata
        if tag == "manifest" and key == "package":
            out["package"] = str(value)
        elif tag == "manifest" and key == "versionCode":
            out["version_code"] = _int(value)
        elif tag == "manifest" and key == "versionName":
            out["version_name"] = str(value)
        elif tag == "uses-sdk" and key == "minSdkVersion":
            out["min_sdk"] = _int(value)
```

- [ ] **Step 5: Тесты проходят**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_apkinfo.py`
Expected: 8 passed.

- [ ] **Step 6: Коммит**

```bash
git add backend/farm/apkinfo.py backend/tests/_axml.py backend/tests/test_apkinfo.py
git commit -m "Разбор APK без aapt: пакет и версия из манифеста

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Библиотека APK (`apklib`)

**Files:**
- Create: `backend/farm/apklib.py`
- Test: `backend/tests/test_apklib.py`

**Interfaces:**
- Consumes: `apkinfo.read`, `apkinfo.ApkError` (Task 1); `farm.control.install(serial, apk_path) -> str`; `farm.api.bulk.failure(message) -> {"reason": str, ...}`; `farm.scenarios.discover()`; `farm.recorder.save.load_recipe(key)`.
- Produces:
  - `apklib.PACKAGE_RE`
  - `apklib.list_all() -> list[dict]` — `[{package, name, version_name, version_code, min_sdk, size, sha256, added}]`, по имени
  - `apklib.get(package) -> dict | None` (те же ключи)
  - `apklib.name_of(package) -> str` — имя из библиотеки или из пакета
  - `apklib.add(src: Path, name: str = "") -> dict` — запись + `"replaced": bool`; бросает `apkinfo.ApkError`
  - `apklib.rename(package, name) -> dict | None`, `apklib.remove(package) -> bool`
  - `apklib.usage() -> dict[str, int]`
  - `apklib.install(serial, package, check_cancel=lambda: None) -> str`; бросает `apklib.InstallFailed(str)` с текстом для человека
  - `apklib.SLOTS` — `threading.BoundedSemaphore(4)`

- [ ] **Step 1: Падающие тесты**

`backend/tests/test_apklib.py`:

```python
"""Библиотека APK: файлы, индекс, установка под семафором."""
import threading
import time

import pytest

import _axml
from farm import apkinfo, apklib, config


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    return tmp_path


def _apk(tmp_path, name="vk.apk", **kw):
    args = dict(package="com.vkontakte.android", version_code=1, version_name="8.40")
    args.update(kw)
    return _axml.apk(tmp_path / name, **args)


def test_добавить_и_прочитать(lib):
    out = apklib.add(_apk(lib))
    assert out["package"] == "com.vkontakte.android"
    assert out["name"] == "VK" and out["version_name"] == "8.40" and out["replaced"] is False
    assert (lib / "data" / "apks" / "com.vkontakte.android.apk").is_file()
    assert apklib.get("com.vkontakte.android")["size"] > 0
    assert [a["package"] for a in apklib.list_all()] == ["com.vkontakte.android"]


def test_новый_apk_заменяет_старый_и_хранит_имя(lib):
    apklib.add(_apk(lib))
    apklib.rename("com.vkontakte.android", "ВК рабочий")
    out = apklib.add(_apk(lib, name="vk2.apk", version_code=2, version_name="8.41"))
    assert out["replaced"] is True and out["name"] == "ВК рабочий"
    assert apklib.get("com.vkontakte.android")["version_name"] == "8.41"
    assert len(apklib.list_all()) == 1


def test_битый_файл_не_попадает_в_библиотеку(lib):
    bad = lib / "x.apk"
    bad.write_bytes(b"nope")
    with pytest.raises(apkinfo.ApkError):
        apklib.add(bad)
    assert apklib.list_all() == []


def test_имя_по_пакету(lib):
    assert apklib.name_of("org.telegram.messenger") == "Telegram"
    assert apklib.name_of("com.example.superapp") == "Superapp"


def test_удалить(lib):
    apklib.add(_apk(lib))
    assert apklib.remove("com.vkontakte.android") is True
    assert apklib.get("com.vkontakte.android") is None
    assert not (lib / "data" / "apks" / "com.vkontakte.android.apk").exists()
    assert apklib.remove("com.vkontakte.android") is False


def test_счётчик_использования(lib, monkeypatch):
    from farm import scenarios
    from farm.recorder import save

    class Sc:
        def __init__(self, key):
            self.key = key

    recipes = {
        "a": {"steps": [{"kind": "ensure_app", "args": {"package": "com.vk"}},
                        {"kind": "if_phone", "args": {"check": "app_installed", "package": "com.vk"}}]},
        "b": {"steps": [{"kind": "if_phone", "args": {"check": "offline"}}]},
        "c": None,
    }
    monkeypatch.setattr(scenarios, "discover", lambda force=False: [Sc(k) for k in recipes])
    monkeypatch.setattr(save, "load_recipe", lambda key: recipes[key])
    assert apklib.usage() == {"com.vk": 1}


def test_установка_ставит_файл_из_библиотеки(lib, monkeypatch):
    apklib.add(_apk(lib))
    calls = []
    monkeypatch.setattr(apklib.control, "install", lambda s, p: calls.append((s, p)) or "Success")
    assert apklib.install("S1", "com.vkontakte.android") == "Success"
    assert calls[0][0] == "S1" and calls[0][1].endswith("com.vkontakte.android.apk")


def test_причина_отказа_словами(lib, monkeypatch):
    apklib.add(_apk(lib))
    monkeypatch.setattr(apklib.control, "install",
                        lambda s, p: "Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]")
    with pytest.raises(apklib.InstallFailed, match="места"):
        apklib.install("S1", "com.vkontakte.android")


def test_нет_в_библиотеке(lib):
    with pytest.raises(apklib.InstallFailed, match="нет в библиотеке"):
        apklib.install("S1", "com.nope")


def test_не_больше_четырёх_установок_разом(lib, monkeypatch):
    apklib.add(_apk(lib))
    now, peak, lock = [0], [0], threading.Lock()

    def slow(serial, path):
        with lock:
            now[0] += 1
            peak[0] = max(peak[0], now[0])
        time.sleep(0.05)
        with lock:
            now[0] -= 1
        return "Success"

    monkeypatch.setattr(apklib.control, "install", slow)
    threads = [threading.Thread(target=apklib.install, args=(f"S{i}", "com.vkontakte.android"))
               for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 4


def test_отмена_в_очереди(lib, monkeypatch):
    apklib.add(_apk(lib))
    for _ in range(4):
        apklib.SLOTS.acquire()
    try:
        class Stop(Exception):
            pass

        def cancel():
            raise Stop

        with pytest.raises(Stop):
            apklib.install("S1", "com.vkontakte.android", check_cancel=cancel)
    finally:
        for _ in range(4):
            apklib.SLOTS.release()
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_apklib.py`
Expected: FAIL — `ImportError: cannot import name 'apklib'`.

- [ ] **Step 3: Реализация**

`backend/farm/apklib.py`:

```python
"""Библиотека APK фермы: приложения, которые сценарий ставит сам.

Один файл на приложение: data/apks/<пакет>.apk. Новый APK того же пакета
заменяет старый — сценарии ссылаются на пакет, а не на файл, и сразу
начинают ставить новую версию. Индекс — data/apks.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from . import apkinfo, config, control

PACKAGE_RE = re.compile(r"^[A-Za-z][\w]*(\.[A-Za-z][\w]*)+$")
# 40 телефонов × 100 МБ по USB разом кладут хаб: половина установок
# отваливается по таймауту. Остальные ждут своей очереди.
SLOTS = threading.BoundedSemaphore(4)
_lock = threading.Lock()

KNOWN = {"com.vkontakte.android": "VK", "com.instagram.android": "Instagram",
         "com.zhiliaoapp.musically": "TikTok", "com.ss.android.ugc.trill": "TikTok",
         "org.telegram.messenger": "Telegram"}
_NOISE = {"com", "org", "net", "ru", "app", "android", "mobile", "client"}

# Причины отказа установки — те же коды, что у массовой установки (bulk.failure).
REASON_WORDS = {
    "no_space": "на телефоне не хватило места",
    "signature": "на телефоне стоит другая сборка приложения — удалите её вручную "
                 "(данные приложения пропадут)",
    "old_android": "Android на телефоне слишком старый для этого приложения",
    "downgrade": "на телефоне уже стоит более новая версия",
    "abi": "приложение не подходит к этому телефону",
    "blocked": "телефон запретил установку — проверьте экран",
    "bad_apk": "файл приложения повреждён",
    "offline": "телефон отключился",
    "not_found": "телефон отключился",
    "timeout": "установка не уложилась во время",
}


class InstallFailed(Exception):
    """Установка не удалась; текст — для человека."""


def _dir() -> Path:
    return Path(config.DATA_DIR) / "apks"


def _index_path() -> Path:
    return Path(config.DATA_DIR) / "apks.json"


def path_of(package: str) -> Path:
    if not PACKAGE_RE.match(package or ""):
        raise ValueError(f"не похоже на приложение: {package!r}")
    return _dir() / f"{package}.apk"


def _load() -> dict:
    try:
        data = json.loads(_index_path().read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(index: dict) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)


def name_of(package: str) -> str:
    entry = _load().get(package)
    if entry and entry.get("name"):
        return entry["name"]
    if package in KNOWN:
        return KNOWN[package]
    parts = [p for p in str(package).split(".") if p.lower() not in _NOISE] or [str(package)]
    word = parts[-1]
    return word[:1].upper() + word[1:]


def list_all() -> list[dict]:
    rows = [{"package": k, **v} for k, v in _load().items()]
    return sorted(rows, key=lambda r: r.get("name", "").lower())


def get(package: str) -> dict | None:
    entry = _load().get(package)
    return {"package": package, **entry} if entry else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def add(src: Path, name: str = "") -> dict:
    """Положить APK в библиотеку (заменив прежний того же пакета)."""
    info = apkinfo.read(src)
    package = info["package"]
    dest = path_of(package)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    shutil.copyfile(src, tmp)
    sha = _sha256(tmp)
    with _lock:
        os.replace(tmp, dest)
        index = _load()
        old = index.get(package) or {}
        index[package] = {
            "name": (name or "").strip()[:60] or old.get("name") or name_of(package),
            "version_name": info["version_name"],
            "version_code": info["version_code"],
            "min_sdk": info["min_sdk"],
            "size": dest.stat().st_size,
            "sha256": sha,
            "added": time.time(),
        }
        _save(index)
        return {"package": package, **index[package], "replaced": bool(old)}


def rename(package: str, name: str) -> dict | None:
    name = (name or "").strip()[:60]
    with _lock:
        index = _load()
        if package not in index or not name:
            return None
        index[package]["name"] = name
        _save(index)
        return {"package": package, **index[package]}


def remove(package: str) -> bool:
    with _lock:
        index = _load()
        if package not in index:
            return False
        del index[package]
        _save(index)
        try:
            path_of(package).unlink()
        except (OSError, ValueError):
            pass
        return True


def usage() -> dict[str, int]:
    """Сколько сохранённых сценариев ссылается на каждое приложение."""
    from . import scenarios
    from .recorder import save
    out: dict[str, int] = {}
    for sc in scenarios.discover():
        recipe = save.load_recipe(sc.key) or {}
        used = {(s.get("args") or {}).get("package")
                for s in recipe.get("steps") or []
                if s.get("kind") in ("ensure_app", "if_phone")}
        for package in used - {None, ""}:
            out[package] = out.get(package, 0) + 1
    return out


def _words(text: str) -> str:
    from .api.bulk import failure   # здесь, не сверху: api импортирует apklib
    reason = failure(text)["reason"]
    return REASON_WORDS.get(reason, "телефон отказался ставить приложение")


def install(serial: str, package: str,
            check_cancel: Callable[[], None] = lambda: None) -> str:
    """Поставить приложение из библиотеки; ждёт свободного места в очереди."""
    if get(package) is None:
        raise InstallFailed(f"{name_of(package)} нет в библиотеке")
    while not SLOTS.acquire(timeout=0.5):
        check_cancel()
    try:
        check_cancel()
        try:
            out = control.install(serial, str(path_of(package))).strip()
        except Exception as e:  # noqa: BLE001 — adb: таймаут, отключение
            raise InstallFailed(_words(str(e))) from None
        if "Failure [" in out or "INSTALL_FAILED" in out:
            raise InstallFailed(_words(out))
        return out
    finally:
        SLOTS.release()
```

- [ ] **Step 4: Тесты проходят**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_apklib.py`
Expected: 11 passed.

- [ ] **Step 5: Коммит**

```bash
git add backend/farm/apklib.py backend/tests/test_apklib.py
git commit -m "Библиотека APK: хранение, замена, установка не больше 4 разом

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: REST `/api/apks`

**Files:**
- Create: `backend/farm/api/apks.py`
- Modify: `backend/farm/api/__init__.py` (импорт + `include_router`)
- Test: `backend/tests/test_api_apks.py`

**Interfaces:**
- Consumes: `apklib.*` (Task 2); `bulk._upload(request, name) -> Path`, `bulk._discard(path)`.
- Produces: `GET /api/apks` → `[{...запись, "used": int}]`; `POST /api/apks?name=<файл>` (тело — APK) → запись + `replaced`; `PATCH /api/apks/{package}` `{name}` → запись; `DELETE /api/apks/{package}` → `{"ok": true}`.

- [ ] **Step 1: Падающие тесты**

`backend/tests/test_api_apks.py`:

```python
"""REST библиотеки APK. TestClient недоступен — зовём функции роутера."""
import asyncio

import pytest
from fastapi import HTTPException

import _axml
from farm import apklib, config
from farm.api import apks as api_apks


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(apklib, "usage", lambda: {"com.vkontakte.android": 3})
    return tmp_path


class Req:
    """Минимум Request для bulk._upload: заголовки и поток тела."""

    def __init__(self, data: bytes):
        self.headers = {"content-length": str(len(data))}
        self._data = data

    async def stream(self):
        yield self._data


def _upload(data, name="vk.apk"):
    return asyncio.run(api_apks.upload(Req(data), name=name))


def _vk(lib, **kw):
    args = dict(package="com.vkontakte.android", version_code=5, version_name="8.40")
    args.update(kw)
    return _axml.apk(lib / "src.apk", **args).read_bytes()


def test_загрузка_и_список(lib):
    out = _upload(_vk(lib))
    assert out["package"] == "com.vkontakte.android" and out["replaced"] is False
    rows = api_apks.list_apks()
    assert rows[0]["used"] == 3 and rows[0]["version_name"] == "8.40"


def test_не_apk_даёт_400(lib):
    with pytest.raises(HTTPException) as e:
        _upload(b"not a zip")
    assert e.value.status_code == 400 and "не архив" in e.value.detail


def test_набор_apks_пока_не_поддерживаем(lib):
    with pytest.raises(HTTPException) as e:
        _upload(b"PK...", name="vk.xapk")
    assert e.value.status_code == 400 and ".apks" in e.value.detail


def test_переименовать_и_удалить(lib):
    _upload(_vk(lib))
    assert api_apks.rename_apk("com.vkontakte.android", {"name": "ВК"})["name"] == "ВК"
    with pytest.raises(HTTPException) as e:
        api_apks.rename_apk("com.vkontakte.android", {"name": "  "})
    assert e.value.status_code == 400
    assert api_apks.delete_apk("com.vkontakte.android") == {"ok": True}
    with pytest.raises(HTTPException) as e:
        api_apks.delete_apk("com.vkontakte.android")
    assert e.value.status_code == 404
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_api_apks.py`
Expected: FAIL — `ImportError: cannot import name 'apks'`.

- [ ] **Step 3: Реализация**

`backend/farm/api/apks.py`:

```python
"""Библиотека APK: приложения, которые сценарий ставит сам (шаг ensure_app)."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request

from .. import apkinfo, apklib
from . import bulk

router = APIRouter(prefix="/api/apks")

_BUNDLES = (".apks", ".xapk", ".apkm")


@router.get("")
def list_apks():
    used = apklib.usage()
    return [{**a, "used": used.get(a["package"], 0)} for a in apklib.list_all()]


@router.post("")
async def upload(request: Request, name: str = Query("app.apk")):
    """Тело запроса — сам APK. Тот же пакет заменяет прежний файл."""
    if name.lower().endswith(_BUNDLES):
        raise HTTPException(400, "наборы .apks/.xapk пока не поддерживаются — нужен один файл .apk")
    tmp = await bulk._upload(request, name)
    try:
        return apklib.add(tmp)
    except apkinfo.ApkError as e:
        raise HTTPException(400, str(e))
    finally:
        bulk._discard(tmp)


@router.patch("/{package}")
def rename_apk(package: str, payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "впишите название")
    out = apklib.rename(package, name)
    if out is None:
        raise HTTPException(404, "такого приложения нет в библиотеке")
    return out


@router.delete("/{package}")
def delete_apk(package: str):
    if not apklib.remove(package):
        raise HTTPException(404, "такого приложения нет в библиотеке")
    return {"ok": True}
```

В `backend/farm/api/__init__.py`: в импорт добавить `apks` (`from . import (accounts, apks, bulk, …)`) и строку `router.include_router(apks.router)` после `router.include_router(bulk.router)`.

- [ ] **Step 4: Тесты проходят и сервер импортируется**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_api_apks.py && ../.venv/bin/python -c "import farm.api"`
Expected: 4 passed, импорт без ошибок.

- [ ] **Step 5: Коммит**

```bash
git add backend/farm/api/apks.py backend/farm/api/__init__.py backend/tests/test_api_apks.py
git commit -m "API библиотеки APK: загрузка, список, переименование, удаление

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Факты о телефоне (`facts`)

**Files:**
- Create: `backend/farm/control/facts.py`
- Test: `backend/tests/test_phone_facts.py`

**Interfaces:**
- Produces:
  - `facts.FactUnknown(Exception)` — факт не прочитался (повод для повтора)
  - `facts.parse_app_version(text) -> {"name": str, "code": int} | None`; `facts.app_version(serial, package)` — то же с телефона (adb ошибка → `AdbError`)
  - `facts.parse_free_gb(text) -> float | None`; `facts.free_gb(serial) -> float` (не разобрали → `FactUnknown`)
  - `facts.battery_level(serial) -> int` (нет данных → `FactUnknown`)
  - `facts.online(serial) -> bool`
  - `facts.version_lt(have: str, want: str) -> bool` (нечитаемо → `ValueError`)

- [ ] **Step 1: Падающие тесты**

`backend/tests/test_phone_facts.py`:

```python
"""Факты о телефоне: разбор вывода dumpsys/df, сравнение версий."""
import pytest

from farm.control import facts

DUMPSYS = """Packages:
  Package [com.vkontakte.android] (5c1d2e):
    userId=10213
    versionCode=24015 minSdk=26 targetSdk=34
    versionName=8.40.1
  Hidden system packages:
    versionCode=100 minSdk=21
    versionName=1.0
"""

DF_TOYBOX = """Filesystem       1K-blocks    Used Available Use% Mounted on
/dev/block/dm-8  114639928 6553676 108086252   6% /data
"""

DF_OLD = """Filesystem               Size     Used     Free   Blksize
/data                   25.0G     6.0G    19.5G   4096
"""


def test_версия_приложения():
    assert facts.parse_app_version(DUMPSYS) == {"name": "8.40.1", "code": 24015}


def test_не_установлено():
    assert facts.parse_app_version("Unable to find package: com.nope\n") is None


@pytest.mark.parametrize("text,gb", [(DF_TOYBOX, 103.08), (DF_OLD, 19.5)])
def test_свободное_место(text, gb):
    assert facts.parse_free_gb(text) == pytest.approx(gb, abs=0.01)


def test_место_не_разобрать():
    assert facts.parse_free_gb("df: /data: Permission denied") is None


@pytest.mark.parametrize("have,want,lt", [
    ("8.38.2", "8.40", True), ("8.40", "8.40", False), ("8.40.1", "8.40", False),
    ("10.0", "9.9.9", False), ("8.40-beta", "8.41", True), ("v8.4", "8.40", True),
])
def test_сравнение_версий(have, want, lt):
    assert facts.version_lt(have, want) is lt


def test_нечитаемая_версия():
    with pytest.raises(ValueError, match="не понять версию"):
        facts.version_lt("beta", "8.40")


def test_интернет(monkeypatch):
    monkeypatch.setattr(facts.adb, "shell", lambda serial, cmd, timeout=None: "0\n")
    assert facts.online("S") is True
    monkeypatch.setattr(facts.adb, "shell", lambda serial, cmd, timeout=None: "1\n")
    assert facts.online("S") is False


def test_заряд(monkeypatch):
    monkeypatch.setattr(facts.adb, "battery", lambda serial: {"level": 17})
    assert facts.battery_level("S") == 17
    monkeypatch.setattr(facts.adb, "battery", lambda serial: {})
    with pytest.raises(facts.FactUnknown):
        facts.battery_level("S")
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_phone_facts.py`
Expected: FAIL — `ImportError: cannot import name 'facts'`.

- [ ] **Step 3: Реализация**

`backend/farm/control/facts.py`:

```python
"""Системные факты о телефоне для проверок сценария (блок «Если на
телефоне», шаг «Приложение готово»): версия приложения, свободное место,
интернет, заряд."""
from __future__ import annotations

import re
import shlex

from .. import adb

_VNAME = re.compile(r"versionName=(\S+)")
_VCODE = re.compile(r"versionCode=(\d+)")
_SIZE = re.compile(r"^([\d.]+)([KMGT]?)$", re.I)
# Яндекс — запасной: часть сетей режет 8.8.8.8, а интернет при этом есть.
PING = ("ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1 || "
        "ping -c 1 -W 3 77.88.8.8 >/dev/null 2>&1; echo $?")


class FactUnknown(Exception):
    """Факт не прочитался — телефон ответил не то, что ждали."""


def parse_app_version(text: str) -> dict | None:
    """Первый блок пакета: у обновлённого системного приложения ниже идёт
    «Hidden system packages» со старой версией — её не берём."""
    name, code = _VNAME.search(text or ""), _VCODE.search(text or "")
    if not name and not code:
        return None
    return {"name": name.group(1) if name else "", "code": int(code.group(1)) if code else 0}


def app_version(serial: str, package: str) -> dict | None:
    out = adb.shell(serial, ["dumpsys", "package", shlex.quote(package)], timeout=15)
    return parse_app_version(out)


def _gb(value: str) -> float | None:
    m = _SIZE.match(value or "")
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).upper()
    return n * {"": 1 / 1024 / 1024, "K": 1 / 1024 / 1024, "M": 1 / 1024,
                "G": 1, "T": 1024}[unit]


def parse_free_gb(text: str) -> float | None:
    """toybox: «1K-blocks … Available»; старый toolbox: «Size Used Free» с G/M."""
    lines = [line.split() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    head, row = lines[0], lines[-1]
    for col in ("Available", "Avail", "Free"):
        if col in head:
            i = head.index(col)
            if i >= len(row):
                return None
            value = row[i]
            if value.isdigit() and "1K-blocks" in head:
                return round(int(value) / 1024 / 1024, 2)
            return _gb(value)
    return None


def free_gb(serial: str) -> float:
    value = parse_free_gb(adb.shell(serial, ["df", "/data"], timeout=15))
    if value is None:
        raise FactUnknown("свободное место")
    return value


def battery_level(serial: str) -> int:
    level = adb.battery(serial).get("level")
    if level is None:
        raise FactUnknown("заряд")
    return int(level)


def online(serial: str) -> bool:
    lines = adb.shell(serial, PING, timeout=15).strip().splitlines()
    return bool(lines) and lines[-1].strip() == "0"


def _key(version: str) -> tuple | None:
    parts = re.findall(r"\d+", version or "")
    return tuple(int(p) for p in parts) if parts else None


def version_lt(have: str, want: str) -> bool:
    a, b = _key(have), _key(want)
    if a is None or b is None:
        raise ValueError(f"не понять версию: «{have or '?'}» и «{want or '?'}»")
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) < b + (0,) * (n - len(b))
```

Примечание: `PING` — строка, а не список: `adb.shell` склеивает список пробелами и отдаёт `sh` телефона; `||` и `;` должны дойти до него как есть.

- [ ] **Step 4: Тесты проходят**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_phone_facts.py`
Expected: всё зелёное (14 тестов с параметрами).

- [ ] **Step 5: Коммит**

```bash
git add backend/farm/control/facts.py backend/tests/test_phone_facts.py
git commit -m "Факты о телефоне: версия приложения, место, интернет, заряд

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Схема шагов `if_phone` и `ensure_app`

**Files:**
- Modify: `backend/farm/recorder/steps.py` (`ARGS`, `BLOCKS`, `NUMERIC`, `BOOLEAN`, `PARAMETRIZABLE`, `FLEXIBLE`, `_LABELS`, `label_of`, `normalize_step`, `schema`)
- Modify: `backend/tests/test_recipe_schema.py:9` (список блоков)
- Test: `backend/tests/test_phone_steps.py`

**Interfaces:**
- Consumes: `farm.accounts.PLATFORMS`; `apklib.PACKAGE_RE` (Task 2).
- Produces:
  - шаг `{"kind": "if_phone", "args": {"span": int, "check": str, "negate": bool, + поля проверки}}`; лишние поля проверки вычищаются
  - шаг `{"kind": "ensure_app", "args": {"package": str, "install": bool, ["min_version": str]}}`
  - `steps.PHONE_CHECKS: dict[str, tuple[str, ...]]` — `{"app_installed": ("package",), "app_older": ("package", "version"), "battery_below": ("percent",), "offline": (), "space_below": ("gb",), "no_account": ("platform",)}`
  - `steps.VERSION_RE`
  - `schema()["phone_checks"]` — `{check: [поля]}`

- [ ] **Step 1: Падающие тесты**

`backend/tests/test_phone_steps.py`:

```python
"""Схема новых шагов: блок «Если на телефоне» и «Приложение готово»."""
import pytest

from farm.recorder import steps


def phone(**args):
    return steps.normalize_step({"kind": "if_phone", "args": {"span": 1, **args}})


def test_приложение_есть():
    s = phone(check="app_installed", package="com.vk.app", percent=50)
    assert s["args"] == {"span": 1, "check": "app_installed", "package": "com.vk.app",
                         "negate": False}


def test_версия_ниже():
    s = phone(check="app_older", package="com.vk.app", version="8.40", negate=True)
    assert s["args"]["version"] == "8.40" and s["args"]["negate"] is True


@pytest.mark.parametrize("args,msg", [
    ({"check": "dance"}, "условие"),
    ({"check": "app_installed"}, "приложение"),
    ({"check": "app_installed", "package": "vk"}, "приложение"),
    ({"check": "app_older", "package": "com.vk.app", "version": "новая"}, "версия"),
    ({"check": "battery_below", "percent": 0}, "заряд"),
    ({"check": "space_below", "gb": 0}, "место"),
    ({"check": "no_account", "platform": "ok"}, "аккаунт"),
])
def test_ошибки_понятные(args, msg):
    with pytest.raises(steps.StepError, match=msg):
        phone(**args)


def test_заряд_и_место_числа():
    assert phone(check="battery_below", percent="20")["args"]["percent"] == 20
    assert phone(check="space_below", gb="1.5")["args"]["gb"] == 1.5
    assert phone(check="offline")["args"] == {"span": 1, "check": "offline", "negate": False}
    assert phone(check="no_account", platform="vk")["args"]["platform"] == "vk"


def test_блок_вкладывается_как_остальные():
    items = steps.normalize_steps([
        {"kind": "if_phone", "args": {"span": 3, "check": "offline"}},
        {"kind": "sleep", "args": {"seconds": 1}},
        {"kind": "if_seen", "args": {"span": 1}, "any": ['text="OK"']},
        {"kind": "sleep", "args": {"seconds": 1}},
    ])
    assert items[0]["kind"] == "if_phone"
    with pytest.raises(steps.StepError, match="за концом"):
        steps.normalize_steps([{"kind": "if_phone", "args": {"span": 1, "check": "offline"}}])


def test_приложение_готово():
    s = steps.normalize_step({"kind": "ensure_app", "args": {"package": "com.vk.app"}})
    assert s["args"] == {"package": "com.vk.app", "install": True}
    s = steps.normalize_step({"kind": "ensure_app",
                              "args": {"package": "com.vk.app", "min_version": "8.40",
                                       "install": False}, "optional": True})
    assert s["args"] == {"package": "com.vk.app", "min_version": "8.40", "install": False}
    assert s["optional"] is True
    s = steps.normalize_step({"kind": "ensure_app",
                              "args": {"package": "com.vk.app", "min_version": ""}})
    assert "min_version" not in s["args"]
    with pytest.raises(steps.StepError, match="версия"):
        steps.normalize_step({"kind": "ensure_app",
                              "args": {"package": "com.vk.app", "min_version": "x"}})


def test_подписи():
    assert steps.label_of(phone(check="app_installed", package="com.vk.app",
                                negate=True)) == "Если на телефоне нет: com.vk.app"
    assert steps.label_of(phone(check="battery_below", percent=20)) == \
        "Если на телефоне: заряд меньше 20%"
    assert steps.label_of(steps.normalize_step(
        {"kind": "ensure_app", "args": {"package": "com.vk.app", "min_version": "8.40"}})) == \
        "Приложение готово: com.vk.app не ниже 8.40"


def test_схема_для_помощников():
    data = steps.schema()
    assert data["phone_checks"]["app_older"] == ["package", "version"]
    assert "if_phone" in data["blocks"] and "ensure_app" in data["flexible"]
```

В `backend/tests/test_recipe_schema.py` строку 9 заменить на:

```python
    assert data["blocks"] == ["chance", "if_phone", "if_seen", "loop", "until"]
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_phone_steps.py tests/test_recipe_schema.py`
Expected: FAIL — `StepError: неизвестный шаг: 'if_phone'`.

- [ ] **Step 3: Реализация в `steps.py`**

В `ARGS` после `"call"`:

```python
    # «Если на телефоне»: следующие span шагов выполняются, только если факт
    # о телефоне верен (или, с negate, неверен). Поля — по виду check,
    # см. PHONE_CHECKS.
    "if_phone": (("span", "check"), ("negate", "package", "version", "percent", "gb",
                                     "platform")),
    # «Приложение готово»: установлено и не старее min_version; нет — поставить
    # из библиотеки APK фермы (install=False — только проверить).
    "ensure_app": (("package",), ("min_version", "install")),
```

Остальные константы:

```python
BLOCKS = {"loop", "chance", "until", "if_seen", "if_phone"}
```
```python
NUMERIC = {"x", "y", "x1", "y1", "x2", "y2", "duration", "seconds", "timeout",
           "span", "times", "minutes", "pause_min", "pause_max", "percent", "tries", "gb"}
BOOLEAN = {"clear", "watch", "negate", "install"}
```
(если в `NUMERIC` в файле есть ещё ключи — сохранить их, добавить только `"gb"`).

В `PARAMETRIZABLE` добавить `"ensure_app"`, в `FLEXIBLE` — `"ensure_app"`.

После `UNTIL_ON_FAIL = …`:

```python
# Проверки блока «Если на телефоне» и поля, которые каждой нужны.
PHONE_CHECKS = {
    "app_installed": ("package",),
    "app_older": ("package", "version"),
    "battery_below": ("percent",),
    "offline": (),
    "space_below": ("gb",),
    "no_account": ("platform",),
}
_PHONE_FIELDS = ("package", "version", "percent", "gb", "platform")
_PHONE_WORDS = {"package": "приложение", "version": "версия", "percent": "заряд",
                "gb": "место", "platform": "аккаунт"}
VERSION_RE = re.compile(r"^\d+(\.\d+){0,4}$")
```

В `_LABELS` добавить: `"if_phone": "Если на телефоне", "ensure_app": "Приложение готово",`.

В `label_of` перед `elif kind == "call":`:

```python
    elif kind == "if_phone":
        check = args.get("check")
        if check == "app_installed":
            tail = args.get("package", "")
            if args.get("negate"):
                base = "Если на телефоне нет"
        elif check == "app_older":
            tail = f'{args.get("package", "")} старее {args.get("version", "")}'
        elif check == "battery_below":
            tail = f'заряд меньше {_minutes_text(args.get("percent"))}%'
        elif check == "offline":
            tail = "нет интернета"
        elif check == "space_below":
            tail = f'свободно меньше {_minutes_text(args.get("gb"))} ГБ'
        elif check == "no_account":
            tail = f'нет аккаунта {args.get("platform", "")}'
        if args.get("negate") and check != "app_installed":
            base = "Если на телефоне НЕ"
    elif kind == "ensure_app":
        tail = args.get("package", "")
        if args.get("min_version"):
            tail += f' не ниже {args["min_version"]}'
```

В `normalize_step` после `elif kind == "if_seen": _check_if_seen(step["args"])`:

```python
    elif kind == "if_phone":
        _check_if_phone(step["args"])
    elif kind == "ensure_app":
        _check_ensure_app(step["args"])
```

После `_check_if_seen`:

```python
def _check_if_phone(args: dict) -> None:
    _span(args, "«если на телефоне»")
    check = args["check"]
    if check not in PHONE_CHECKS:
        raise StepError(f"«если на телефоне»: условие одно из {', '.join(PHONE_CHECKS)}")
    need = PHONE_CHECKS[check]
    for field in _PHONE_FIELDS:
        if field not in need:
            args.pop(field, None)
        elif args.get(field) in (None, ""):
            raise StepError(f"«если на телефоне»: не задано — {_PHONE_WORDS[field]}")
    from ..apklib import PACKAGE_RE
    if "package" in need and not PACKAGE_RE.match(args["package"]):
        raise StepError("«если на телефоне»: приложение — вида com.example.app")
    if "version" in need and not VERSION_RE.match(args["version"]):
        raise StepError("«если на телефоне»: версия — числа через точку, например 8.40")
    if "percent" in need:
        if not 1 <= args["percent"] <= 99:
            raise StepError("«если на телефоне»: заряд от 1 до 99 %")
        args["percent"] = int(args["percent"])
    if "gb" in need and not 0.1 <= args["gb"] <= 256:
        raise StepError("«если на телефоне»: место от 0.1 до 256 ГБ")
    if "platform" in need:
        from ..accounts import PLATFORMS
        if args["platform"] not in PLATFORMS:
            raise StepError(f"«если на телефоне»: аккаунт одной из платформ {', '.join(PLATFORMS)}")
    args["negate"] = bool(args.get("negate"))


def _check_ensure_app(args: dict) -> None:
    from ..apklib import PACKAGE_RE
    if not PACKAGE_RE.match(args["package"]):
        raise StepError("«приложение готово»: приложение — вида com.example.app")
    version = args.pop("min_version", "") or ""
    if version:
        if not VERSION_RE.match(version):
            raise StepError("«приложение готово»: версия — числа через точку, например 8.40")
        args["min_version"] = version
    args["install"] = bool(args.get("install", True))
```

Порядок ключей в `args` у `ensure_app` должен совпасть с тестом (`package`, `min_version`, `install`): `_args` кладёт ключи в порядке `required + optional`, `_check_ensure_app` вынимает `min_version` и кладёт назад перед `install` — сравнение словарей в тесте от порядка не зависит.

В `schema()` после `"finish_results": …`:

```python
        "phone_checks": {k: list(v) for k, v in PHONE_CHECKS.items()},
```

- [ ] **Step 4: Тесты проходят**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_phone_steps.py tests/test_recipe_schema.py tests/test_recorder_steps.py tests/test_blocks.py`
Expected: всё зелёное.

- [ ] **Step 5: Коммит**

```bash
git add backend/farm/recorder/steps.py backend/tests/test_phone_steps.py backend/tests/test_recipe_schema.py
git commit -m "Схема шагов: блок «Если на телефоне» и «Приложение готово»

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Codegen и предупреждение «нет в библиотеке»

**Files:**
- Modify: `backend/farm/recorder/codegen.py` (`BLOCK_HEADERS`, `_call`)
- Modify: `backend/farm/recorder/validate.py` (параметр `library`)
- Modify: `backend/farm/api/recorder.py:76-93` (передать библиотеку)
- Test: `backend/tests/test_phone_codegen.py`

**Interfaces:**
- Consumes: шаги из Task 5; `apklib.list_all()` (Task 2).
- Produces: строки кода `if [not ]ctx.phone_is("<check>", package=…, version=…, platform=…, percent=…, gb=…):` и `ctx.ensure_app(<package|ctx.params[...]>[, min_version="…"][, install=False])` — их вызывает Task 7. `validate(payload, blocks=None, packages=None, assets=None, library=None)`.

- [ ] **Step 1: Падающие тесты**

`backend/tests/test_phone_codegen.py`:

```python
"""Код новых шагов и предупреждение о приложении вне библиотеки."""
from farm.recorder import codegen, steps
from farm.recorder.validate import validate

META = {"name": "Тест", "description": "", "watch_popups": False}


def body(*raw):
    text = codegen.render(META, {}, [steps.normalize_step(s) for s in raw])
    lines = text.splitlines()
    start = lines.index("def run(ctx):") + 1
    return [line[4:] for line in lines[start:] if line.strip()]


def test_блок_если_на_телефоне():
    assert body(
        {"kind": "if_phone", "args": {"span": 1, "check": "app_installed",
                                      "package": "com.vk.app", "negate": True}},
        {"kind": "sleep", "args": {"seconds": 1}},
    ) == ['if not ctx.phone_is("app_installed", package="com.vk.app"):', "    ctx.sleep(1)"]


def test_числа_и_платформа():
    assert body(
        {"kind": "if_phone", "args": {"span": 1, "check": "battery_below", "percent": 20}},
        {"kind": "finish", "args": {"result": "fail", "reason": "разряжен"}},
    )[0] == 'if ctx.phone_is("battery_below", percent=20):'
    assert body(
        {"kind": "if_phone", "args": {"span": 1, "check": "no_account", "platform": "vk"}},
        {"kind": "sleep", "args": {"seconds": 1}},
    )[0] == 'if ctx.phone_is("no_account", platform="vk"):'


def test_приложение_готово():
    assert body({"kind": "ensure_app", "args": {"package": "com.vk.app"}}) == \
        ['ctx.ensure_app("com.vk.app")']
    assert body({"kind": "ensure_app", "args": {"package": "com.vk.app", "min_version": "8.40",
                                               "install": False}}) == \
        ['ctx.ensure_app("com.vk.app", min_version="8.40", install=False)']
    assert body({"kind": "ensure_app", "args": {"package": "com.vk.app"}, "optional": True})[0] \
        .startswith("ctx.attempt(lambda: ctx.ensure_app(")


def test_предупреждение_нет_в_библиотеке():
    payload = {"meta": META, "params": {},
               "steps": [{"kind": "ensure_app", "args": {"package": "com.vk.app"}}]}
    out = validate(payload, library={"org.telegram.messenger"})
    assert out["ok"] is True
    assert any("нет в библиотеке" in w["text"] for w in out["warnings"])
    assert not validate(payload, library={"com.vk.app"})["warnings"]
    assert not validate(payload)["warnings"]
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_phone_codegen.py`
Expected: FAIL — `KeyError`/`ValueError: неизвестный шаг: if_phone` из codegen и `TypeError: validate() got an unexpected keyword argument 'library'`.

- [ ] **Step 3: Реализация**

`codegen.py`, после `_if_seen`:

```python
def _if_phone(step: dict) -> str:
    """«Если на телефоне»: факт о телефоне, тело — следующие span шагов."""
    args = step["args"]
    parts = [literal(args["check"])]
    for field in ("package", "version", "platform"):
        if field in args:
            parts.append(f"{field}={literal(args[field])}")
    for field in ("percent", "gb"):
        if field in args:
            parts.append(f"{field}={_num(args[field])}")
    return f'if {"not " if args.get("negate") else ""}ctx.phone_is({", ".join(parts)}):'


BLOCK_HEADERS = {"loop": _loop, "chance": _chance, "until": _until, "if_seen": _if_seen,
                 "if_phone": _if_phone}
```

В `_call` перед `if kind == "click":`:

```python
    if kind == "ensure_app":
        parts = [_value(step, literal(args["package"]))]
        if args.get("min_version"):
            parts.append(f'min_version={literal(args["min_version"])}')
        if not args.get("install", True):
            parts.append("install=False")
        return f"ctx.ensure_app({', '.join(parts)})"
```

`validate.py`: сигнатура и докстринг —

```python
def validate(payload: dict, blocks: dict | None = None,
             packages: set | None = None, assets: set | None = None,
             library: set | None = None) -> dict:
    """{ok, errors[], warnings[]}; каждая запись {step, level, text}.

    `blocks` — {ключ: True, если блок загружается}; `packages` — установленные
    на устройстве пакеты (None — устройство не выбрано); `assets` — имена кропов,
    приехавших вместе с запросом; `library` — пакеты в библиотеке APK фермы
    (None — не проверять).
    """
```

в цикле `for i, step in good:` после проверки `launch_app/stop_app`:

```python
        if kind == "ensure_app" and library is not None and not step.get("param") \
                and step["args"]["install"] and step["args"]["package"] not in library:
            add("warning", i, f"приложения {step['args']['package']} нет в библиотеке — "
                              "шаг сможет только проверить; добавьте APK в "
                              "Сценарии → Приложения")
```

`api/recorder.py`, в `validate` перед `return`:

```python
    library = {a["package"] for a in apklib.list_all()}
    return recorder_validate.validate(payload, blocks, packages, assets, library)
```

и импорт `from .. import apklib` рядом с остальными импортами модуля.

- [ ] **Step 4: Тесты проходят**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_phone_codegen.py tests/test_recorder_codegen.py tests/test_recorder_validate.py tests/test_recorder_api.py`
Expected: всё зелёное.

- [ ] **Step 5: Коммит**

```bash
git add backend/farm/recorder/codegen.py backend/farm/recorder/validate.py backend/farm/api/recorder.py backend/tests/test_phone_codegen.py
git commit -m "Код для проверок телефона и предупреждение «нет в библиотеке»

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `ctx.phone_is` и `ctx.ensure_app`

**Files:**
- Modify: `backend/farm/context.py` (импорты; методы после `seen`)
- Test: `backend/tests/test_ctx_phone.py`

**Interfaces:**
- Consumes: `facts.*` (Task 4), `apklib.get/install/name_of/InstallFailed` (Task 2), `accounts.for_device(serial, platform)`.
- Produces: `DeviceContext.phone_is(check, *, package=None, version=None, percent=None, gb=None, platform=None) -> bool`; `DeviceContext.ensure_app(package, min_version=None, install=True) -> None`; падение — `StepFailed` с текстом для человека.

- [ ] **Step 1: Падающие тесты**

`backend/tests/test_ctx_phone.py`:

```python
"""Проверки телефона в сценарии: факты, установка из библиотеки, ошибки словами."""
import pytest

from farm import accounts, apklib
from farm.adb import AdbError
from farm.context import Cancelled, DeviceContext, StepFailed
from farm.control import facts

PKG = "com.vkontakte.android"


@pytest.fixture
def ctx(monkeypatch):
    lines = []
    c = DeviceContext("S", logger=lines.append)
    c.lines = lines
    monkeypatch.setattr(c, "sleep", lambda s: None)
    monkeypatch.setattr(apklib, "name_of", lambda p: "VK")
    return c


def versions(monkeypatch, *seq):
    """app_version отдаёт значения по очереди (исключение — бросает)."""
    it = iter(seq)

    def fake(serial, package):
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(facts, "app_version", fake)


def test_есть_приложение(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.38.2", "code": 1})
    assert ctx.phone_is("app_installed", package=PKG) is True
    assert "VK есть, 8.38.2" in ctx.lines[-1]


def test_версия_ниже_и_нет_приложения(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.38.2", "code": 1}, None)
    assert ctx.phone_is("app_older", package=PKG, version="8.40") is True
    assert ctx.phone_is("app_older", package=PKG, version="8.40") is True   # нет = старее


@pytest.mark.parametrize("check,kw,fact,value,want", [
    ("battery_below", {"percent": 20}, "battery_level", 17, True),
    ("battery_below", {"percent": 20}, "battery_level", 80, False),
    ("offline", {}, "online", False, True),
    ("space_below", {"gb": 1}, "free_gb", 0.4, True),
])
def test_факты(ctx, monkeypatch, check, kw, fact, value, want):
    monkeypatch.setattr(facts, fact, lambda serial: value)
    assert ctx.phone_is(check, **kw) is want


def test_аккаунт(ctx, monkeypatch):
    monkeypatch.setattr(accounts, "for_device", lambda serial, platform: None)
    assert ctx.phone_is("no_account", platform="vk") is True


def test_один_повтор_потом_понятная_ошибка(ctx, monkeypatch):
    versions(monkeypatch, AdbError("timeout"), {"name": "1.0", "code": 1})
    assert ctx.phone_is("app_installed", package=PKG) is True
    versions(monkeypatch, AdbError("timeout"), AdbError("timeout"))
    with pytest.raises(StepFailed, match="не удалось узнать версию"):
        ctx.phone_is("app_installed", package=PKG)


def test_уже_готово(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.41", "code": 1})
    monkeypatch.setattr(apklib, "install", lambda *a, **k: pytest.fail("не ставить"))
    ctx.ensure_app(PKG, min_version="8.40")


def test_нет_ставим_из_библиотеки(ctx, monkeypatch):
    versions(monkeypatch, None, {"name": "8.40", "code": 1})
    monkeypatch.setattr(apklib, "get", lambda p: {"package": p, "version_name": "8.40"})
    calls = []
    monkeypatch.setattr(apklib, "install",
                        lambda serial, package, check_cancel: calls.append(package) or "Success")
    ctx.ensure_app(PKG)
    assert calls == [PKG]
    assert any("ставлю 8.40" in line for line in ctx.lines)


def test_только_проверка(ctx, monkeypatch):
    versions(monkeypatch, None)
    with pytest.raises(StepFailed, match="VK не установлен"):
        ctx.ensure_app(PKG, install=False)


def test_нет_в_библиотеке(ctx, monkeypatch):
    versions(monkeypatch, None)
    monkeypatch.setattr(apklib, "get", lambda p: None)
    with pytest.raises(StepFailed, match="Сценарии → Приложения"):
        ctx.ensure_app(PKG)


def test_в_библиотеке_старее_нужной(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.20", "code": 1})
    monkeypatch.setattr(apklib, "get", lambda p: {"package": p, "version_name": "8.30"})
    monkeypatch.setattr(apklib, "install", lambda *a, **k: pytest.fail("не ставить"))
    with pytest.raises(StepFailed, match="в библиотеке VK 8.30, а нужно не ниже 8.40"):
        ctx.ensure_app(PKG, min_version="8.40")


def test_установка_упала(ctx, monkeypatch):
    versions(monkeypatch, None)
    monkeypatch.setattr(apklib, "get", lambda p: {"package": p, "version_name": "8.40"})

    def boom(serial, package, check_cancel):
        raise apklib.InstallFailed("на телефоне не хватило места")

    monkeypatch.setattr(apklib, "install", boom)
    with pytest.raises(StepFailed, match="VK: на телефоне не хватило места"):
        ctx.ensure_app(PKG)


def test_отмена(monkeypatch):
    c = DeviceContext("S", logger=lambda m: None, cancel_check=lambda: True)
    with pytest.raises(Cancelled):
        c.ensure_app(PKG)
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_ctx_phone.py`
Expected: FAIL — `AttributeError: 'DeviceContext' object has no attribute 'phone_is'`.

- [ ] **Step 3: Реализация**

`context.py`, импорты: к `from . import adb, config, control, …` добавить `accounts, apklib`; отдельной строкой `from .control import facts as phone_facts`; `from .adb import AdbError` (если ещё не импортирован).

Методы — сразу после `seen`:

```python
    # ------------------------------------------------------------ телефон
    def _phone_fact(self, what: str, read):
        """Факт о телефоне с одним повтором. Ложное «нет» вызвало бы лишнюю
        установку, поэтому не угадываем: второй сбой — понятная ошибка."""
        for attempt in range(2):
            self.check_cancel()
            try:
                return read()
            except (AdbError, phone_facts.FactUnknown):
                if attempt:
                    raise StepFailed(f"не удалось узнать {what} — телефон не ответил") from None
                self.sleep(1)

    def _older(self, have: dict | None, want: str | None) -> bool:
        if not want:
            return False
        if have is None:
            return True
        try:
            return phone_facts.version_lt(have["name"], want)
        except ValueError as e:
            raise StepFailed(str(e)) from None

    def phone_is(self, check: str, *, package: str | None = None, version: str | None = None,
                 percent: float | None = None, gb: float | None = None,
                 platform: str | None = None) -> bool:
        """«Если на телефоне»: `if ctx.phone_is("battery_below", percent=20):`."""
        if check in ("app_installed", "app_older"):
            name = apklib.name_of(package)
            have = self._phone_fact(f"версию {name}",
                                    lambda: phone_facts.app_version(self.serial, package))
            seen = f"{name} есть, {have['name']}" if have else f"{name} не установлено"
            result = have is not None if check == "app_installed" else self._older(have, version)
        elif check == "battery_below":
            level = self._phone_fact("заряд", lambda: phone_facts.battery_level(self.serial))
            seen, result = f"заряд {level}%", level < float(percent)
        elif check == "offline":
            up = self._phone_fact("есть ли интернет", lambda: phone_facts.online(self.serial))
            seen, result = ("интернет есть" if up else "интернета нет"), not up
        elif check == "space_below":
            free = self._phone_fact("свободное место", lambda: phone_facts.free_gb(self.serial))
            seen, result = f"свободно {free:.1f} ГБ", free < float(gb)
        elif check == "no_account":
            acc = accounts.for_device(self.serial, platform)
            seen = f"аккаунт {platform} {'привязан' if acc else 'не привязан'}"
            result = acc is None
        else:
            raise ValueError(f"ctx.phone_is: неизвестная проверка {check!r}")
        self.log(f"на телефоне: {seen} → {'да' if result else 'нет'}")
        return result

    def ensure_app(self, package: str, min_version: str | None = None,
                   install: bool = True) -> None:
        """«Приложение готово»: установлено и не старее min_version; нет —
        поставить из библиотеки APK фермы и проверить ещё раз."""
        name = apklib.name_of(package)
        read = lambda: phone_facts.app_version(self.serial, package)  # noqa: E731
        have = self._phone_fact(f"версию {name}", read)
        if have is not None and not self._older(have, min_version):
            self.log(f"{name} готов: {have['name']}")
            return
        why = (f"{name} не установлен" if have is None
               else f"{name} {have['name']}, а нужно не ниже {min_version}")
        if not install:
            raise StepFailed(why)
        lib = apklib.get(package)
        if lib is None:
            raise StepFailed(f"{name} нет в библиотеке — добавьте APK в Сценарии → Приложения")
        if min_version and self._older({"name": lib["version_name"]}, min_version):
            raise StepFailed(f"в библиотеке {name} {lib['version_name']}, "
                             f"а нужно не ниже {min_version}")
        self.log(f"{why} — ставлю {lib['version_name']} из библиотеки")
        try:
            apklib.install(self.serial, package, check_cancel=self.check_cancel)
        except apklib.InstallFailed as e:
            raise StepFailed(f"{name}: {e}") from None
        have = self._phone_fact(f"версию {name}", read)
        if have is None or self._older(have, min_version):
            raise StepFailed(f"{name} после установки всё ещё не готов")
        self.log(f"{name} установлен: {have['name']}")
```

- [ ] **Step 4: Тесты проходят**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_ctx_phone.py tests/test_blocks.py tests/test_blocks_flow.py tests/test_cancel.py`
Expected: всё зелёное.

- [ ] **Step 5: Коммит**

```bash
git add backend/farm/context.py backend/tests/test_ctx_phone.py
git commit -m "Сценарий проверяет телефон и ставит приложение из библиотеки

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Готовое действие «Приложение готово»

**Files:**
- Modify: `backend/farm/recorder/presets.py` (новый пресет после `clear_app`)
- Modify: `backend/tests/test_recorder_presets.py:7-10` (`_dummy` для версии)

**Interfaces:**
- Consumes: шаг `ensure_app` (Task 5).
- Produces: пресет `key="ensure_app"`, inputs `package` (packages=True) и `min_version` (`version=True`, optional). Фронт рисует его в «Действие» без изменений (`recLibPick` уже понимает `packages`/`optional`).

- [ ] **Step 1: Тест**

В `backend/tests/test_recorder_presets.py` заменить `_dummy`:

```python
def _dummy(spec):
    if spec.get("choices"):
        return next(iter(spec["choices"]))   # первый вариант выбора
    if spec.get("version"):
        return "8.40"
    return "1.5" if spec.get("number") else "com.example.app"
```

и добавить в конец:

```python
def test_приложение_готово_по_умолчанию_ставит():
    preset = next(p for p in presets.PRESETS if p["key"] == "ensure_app")
    filled = presets.fill(preset, {"package": "com.a.b", "min_version": ""})
    assert steps.normalize_step(filled[0])["args"] == {"package": "com.a.b", "install": True}
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_recorder_presets.py`
Expected: FAIL — `StopIteration` (пресета нет).

- [ ] **Step 3: Пресет**

В `PRESETS` после `clear_app`:

```python
    {
        "key": "ensure_app",
        "title": "Приложение готово",
        "desc": "Проверить, что приложение стоит, и поставить из библиотеки, если нет",
        "inputs": [_PACKAGE,
                   {"name": "min_version", "label": "Версия не ниже", "hint": "любая",
                    "optional": True, "version": True}],
        "steps": [{"kind": "ensure_app",
                   "args": {"package": "{package}", "min_version": "{min_version}",
                            "install": True}}],
    },
```

- [ ] **Step 4: Тесты проходят**

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_recorder_presets.py`
Expected: всё зелёное.

- [ ] **Step 5: Коммит**

```bash
git add backend/farm/recorder/presets.py backend/tests/test_recorder_presets.py
git commit -m "Готовое действие «Приложение готово»

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Вкладка «Приложения» (библиотека APK во фронте)

**Files:**
- Create: `frontend/js/apklib.js`, `frontend/css/apklib.css`
- Modify: `frontend/index.html` (вкладки в `#view-scen`, новая `#view-apps`, `<link>`, `<script>`, ранний скрипт выбора раздела)
- Modify: `frontend/js/app.js:14,34,55-63` (раздел `apps`)
- Modify: `frontend/js/apppick.js:12-33` (приложения из библиотеки в выборе)
- Modify: `frontend/strings/ru.json`

**Interfaces:**
- Consumes: `/api/apks` (Task 3); `api`, `toast`, `emptyBig`, `armConfirm`, `disableWithReason`, `promptModal`, `setText`, `esc`, `t`.
- Produces: глобалы `APK_LIB = {list, busy}`, `apkList(force) -> Promise<list>`, `apkShow()`, `apkPick()`, `apkUpload(file)`, `apkDrop(ev)`, `apkRename(pkg)`, `apkRemove(btn, pkg)`. `appChoices(serial)` возвращает и приложения библиотеки.

- [ ] **Step 1: Строки** — в `frontend/strings/ru.json` (в алфавитном месте раздела, рядом с другими `a…`):

```json
  "apk.dobavit": "Добавить APK",
  "apk.dobavlen": "{name} {v} добавлен",
  "apk.gruzim": "файл ещё загружается",
  "apk.mb": "{n} МБ",
  "apk.nazvanie": "Название",
  "apk.nazvanie_title": "Название приложения",
  "apk.pereimenovat": "Переименовать",
  "apk.pusto": "Приложений пока нет",
  "apk.pusto_d": "Добавьте APK — сценарий сам поставит его на телефоны, где приложения нет.",
  "apk.razdel": "Приложения для сценариев",
  "apk.sohranit": "Сохранить",
  "apk.stsenarii_tabs": "Сценарии и приложения",
  "apk.tab_prilozheniya": "Приложения",
  "apk.tab_stsenarii": "Сценарии",
  "apk.tolko_apk": "перетащите файл .apk",
  "apk.udaleno": "{name} удалён из библиотеки",
  "apk.udalit": "Удалить",
  "apk.udalit_tochno": "Точно удалить?",
  "apk.udalit_used": "Сценариев: {n} — удалить?",
  "apk.uzhe_gruzim": "дождитесь конца загрузки",
  "apk.v_stsenariyah": "в сценариях: {n}",
  "apk.versiya": "версия {v}",
  "apk.zamenen": "{name} заменён на {v}",
  "apk.zamenit": "Заменить"
```

- [ ] **Step 2: Разметка** — в `frontend/index.html`:

(a) в `#view-scen` заменить `<strong data-t="scen.stsenarii">Сценарии</strong>` на:

```html
            <div class="seg runs-seg" role="tablist" aria-label="Сценарии и приложения" data-t-aria-label="apk.stsenarii_tabs">
                <button class="sm on" role="tab" aria-selected="true"
                        onclick="showView('scen')" data-t="apk.tab_stsenarii">Сценарии</button>
                <button class="sm" role="tab" aria-selected="false"
                        onclick="showView('apps')" data-t="apk.tab_prilozheniya">Приложения</button>
            </div>
```

(b) сразу после закрывающего `</section>` раздела `#view-scen`:

```html
    <!-- Библиотека APK: приложения, которые сценарий ставит сам (шаг
         «Приложение готово»). Вкладка «Сценариев», а не пятый раздел. -->
    <section class="view" id="view-apps" aria-label="Приложения для сценариев" data-t-aria-label="apk.razdel"
             ondragover="event.preventDefault()" ondrop="apkDrop(event)">
        <div class="bar">
            <div class="seg runs-seg" role="tablist" aria-label="Сценарии и приложения" data-t-aria-label="apk.stsenarii_tabs">
                <button class="sm" role="tab" aria-selected="false"
                        onclick="showView('scen')" data-t="apk.tab_stsenarii">Сценарии</button>
                <button class="sm on" role="tab" aria-selected="true"
                        onclick="showView('apps')" data-t="apk.tab_prilozheniya">Приложения</button>
            </div>
            <span class="stat" id="apkCount"></span>
            <span class="sp"></span>
            <button class="sm primary" id="btnApkAdd" onclick="apkPick()" data-t="apk.dobavit">
                <svg class="ic" aria-hidden="true">
                    <use href="#i-upload"/>
                </svg>
                Добавить APK
            </button>
            <input type="file" id="apkFile" accept=".apk" hidden
                   onchange="apkUpload(this.files[0]); this.value=''">
        </div>
        <div class="scroll" id="apkList"></div>
    </section>
```

(c) `<link rel="stylesheet" href="css/apklib.css">` после `css/files.css`; `<script src="js/apklib.js"></script>` после `js/apppick.js`.

(d) ранний скрипт выбора раздела (внизу `<main>`): строку
`var nav = (name === 'deviations' || name === 'schedule') ? 'jobs' : name;` заменить на
`var nav = (name === 'deviations' || name === 'schedule') ? 'jobs' : name === 'apps' ? 'scen' : name;`

- [ ] **Step 3: `app.js`**

```js
const VIEWS = ['fleet', 'device', 'scen', 'apps', 'jobs', 'deviations', 'schedule', 'accounts'];
```
```js
    /* «Проблемы» живут внутри «Запусков», «Приложения» — внутри «Сценариев». */
    const navName = (name === 'deviations' || name === 'schedule') ? 'jobs'
        : name === 'apps' ? 'scen' : name;
```
и после `if (name === 'accounts') loadAccounts();`:
```js
    if (name === 'apps') apkShow();
```

- [ ] **Step 4: `frontend/js/apklib.js`**

```js
'use strict';

/* Библиотека APK: приложения, которые сценарий ставит сам (шаг «Приложение
   готово»). Одно приложение — один файл: новый APK того же приложения
   заменяет старый, и сценарии сразу ставят новую версию. */

const APK_LIB = {list: null, busy: false};

async function apkList(force) {
    if (APK_LIB.list && !force) return APK_LIB.list;
    APK_LIB.list = await api('/api/apks');
    return APK_LIB.list;
}

function apkShow() {
    apkRender();
    apkList(true).then(apkRender).catch(e => toast(e.message, 'bad'));
}

function apkSize(bytes) {
    return t('apk.mb', {n: Math.max(1, Math.round((bytes || 0) / 1048576))});
}

function apkRender() {
    const box = $('apkList');
    if (!box) return;
    const list = APK_LIB.list;
    setText($('apkCount'), list && list.length ? String(list.length) : '');
    if (!list) return;
    if (!list.length) {
        box.innerHTML = emptyBig({art: 'device', title: esc(t('apk.pusto')), text: esc(t('apk.pusto_d')),
            action: {onClick: 'apkPick()', icon: 'upload', label: esc(t('apk.dobavit'))}});
        return;
    }
    box.innerHTML = `<div class="apk-list">${list.map(a => `
      <div class="apk-row">
        <svg class="ic apk-ic" aria-hidden="true"><use href="#i-phone"/></svg>
        <div class="apk-main">
          <b>${esc(a.name)}</b>
          <span title="${esc(a.package)}">${esc(t('apk.versiya', {v: a.version_name || a.version_code}))}
            · ${esc(apkSize(a.size))}${a.used ? ' · ' + esc(t('apk.v_stsenariyah', {n: a.used})) : ''}</span>
        </div>
        <span class="apk-acts">
          <button class="sm" onclick="apkRename('${esc(a.package)}')">${esc(t('apk.pereimenovat'))}</button>
          <button class="sm" onclick="apkPick()">${esc(t('apk.zamenit'))}</button>
          <button class="sm danger" onclick="apkRemove(this, '${esc(a.package)}')"><span>${esc(t('apk.udalit'))}</span></button>
        </span>
      </div>`).join('')}</div>`;
}

function apkPick() {
    if (APK_LIB.busy) return toast(t('apk.uzhe_gruzim'), 'bad');
    $('apkFile').click();
}

function apkDrop(ev) {
    ev.preventDefault();
    const file = [...((ev.dataTransfer && ev.dataTransfer.files) || [])].find(f => /\.apk$/i.test(f.name));
    if (!file) return toast(t('apk.tolko_apk'), 'bad');
    apkUpload(file);
}

async function apkUpload(file) {
    if (!file) return;
    if (APK_LIB.busy) return toast(t('apk.uzhe_gruzim'), 'bad');
    APK_LIB.busy = true;
    const btn = $('btnApkAdd');
    disableWithReason(btn, true, t('apk.gruzim'));
    try {
        const res = await api('/api/apks?name=' + encodeURIComponent(file.name), {method: 'POST', body: file});
        const words = {name: res.name, v: res.version_name};
        toast(res.replaced ? t('apk.zamenen', words) : t('apk.dobavlen', words), 'ok');
        await apkList(true);
        apkRender();
    } catch (e) {
        toast(e.message, 'bad');
    } finally {
        APK_LIB.busy = false;
        disableWithReason(btn, false);
    }
}

function apkRename(pkg) {
    const a = (APK_LIB.list || []).find(x => x.package === pkg);
    promptModal(t('apk.nazvanie_title'), t('apk.nazvanie'), a ? a.name : '', t('apk.sohranit'), async name => {
        if (!name) return;
        try {
            await api('/api/apks/' + encodeURIComponent(pkg), {
                method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name}),
            });
            apkShow();
        } catch (e) {
            toast(e.message, 'bad');
        }
    });
}

async function apkRemove(btn, pkg) {
    const a = (APK_LIB.list || []).find(x => x.package === pkg);
    if (!armConfirm(btn, a && a.used ? t('apk.udalit_used', {n: a.used}) : t('apk.udalit_tochno'))) return;
    try {
        await api('/api/apks/' + encodeURIComponent(pkg), {method: 'DELETE'});
        toast(t('apk.udaleno', {name: a ? a.name : pkg}), 'ok');
        apkShow();
    } catch (e) {
        toast(e.message, 'bad');
    }
}
```

- [ ] **Step 5: `frontend/css/apklib.css`**

```css
/* Библиотека APK (apklib.js). Действия строки тихие, пока строку не навели:
   в списке из десяти приложений тридцать кнопок разом — шум. */
#apkList .apk-list {
    display: grid;
    gap: var(--s1);
    padding: var(--s3) var(--s4);
}

.apk-row {
    display: flex;
    align-items: center;
    gap: var(--s3);
    padding: var(--s2) var(--s3);
    border-radius: var(--r2);
    border-bottom: 1px solid var(--line-soft);
}

.apk-row:hover,
.apk-row:focus-within {
    background: var(--panel2);
}

.apk-ic {
    flex: none;
    color: var(--dim);
}

.apk-main {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    line-height: var(--lh);
}

.apk-main b {
    font-size: var(--fs-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.apk-main span {
    font-size: var(--fs-2);
    color: var(--dim);
}

.apk-acts {
    display: flex;
    gap: var(--s1);
    flex: none;
    opacity: .45;
    transition: opacity var(--fast) var(--ease);
}

.apk-row:hover .apk-acts,
.apk-row:focus-within .apk-acts {
    opacity: 1;
}
```

- [ ] **Step 6: Выбор приложения видит библиотеку** — в `frontend/js/apppick.js` заменить `appChoices`:

```js
/* [{package, label}] по телефону + приложения из библиотеки APK: шагу
   «Приложение готово» нужно выбрать и то, чего на телефоне ещё нет.
   Кэш на телефон: форма открывается часто. */
async function appChoices(serial) {
    let lib = [];
    try {
        lib = (await apkList()).map(a => ({package: a.package, label: a.name}));
    } catch (e) {
        lib = [];
    }
    if (!serial) return lib;
    if (!APP_PICK.byDevice[serial]) {
        let rows = [];
        try {
            rows = await api(`/api/devices/${serial}/apps`);
        } catch (e) {
            try {
                rows = (await api(`/api/devices/${serial}/packages`)).map(pkg => ({package: pkg}));
            } catch (e2) {
                rows = [];
            }
        }
        APP_PICK.byDevice[serial] = rows.map(r => ({
            package: r.package,
            label: r.label || recApp(r.package).replace(/[«»]/g, ''),
        }));
    }
    const list = APP_PICK.byDevice[serial].slice();
    for (const a of lib) if (!list.some(x => x.package === a.package)) list.push(a);
    return list.sort((a, b) => (REC_APPS[a.package] ? 0 : 1) - (REC_APPS[b.package] ? 0 : 1)
        || a.label.localeCompare(b.label, 'ru'));
}
```

- [ ] **Step 7: Проверки**

Run: `node --check frontend/js/apklib.js && node --check frontend/js/apppick.js && node --check frontend/js/app.js && cd backend && ../.venv/bin/python -m pytest -q tests/test_strings.py`
Expected: синтаксис чистый, `test_strings` зелёный.

- [ ] **Step 8: Коммит**

```bash
git add frontend/js/apklib.js frontend/css/apklib.css frontend/index.html frontend/js/app.js frontend/js/apppick.js frontend/strings/ru.json
git commit -m "Вкладка «Приложения»: библиотека APK в разделе сценариев

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Конструктор — блок «Если на телефоне» и шаг «Приложение готово»

**Files:**
- Modify: `frontend/js/blocks.js` (`BLOCK_KINDS`, `blockPayloadArgs`, `blockLabel`, `blockCode`, `recBlockEditor`, `recBlockSet`, `recIfSeenElse`, петля графа)
- Modify: `frontend/js/addstep.js` (группа `phone`)
- Modify: `frontend/js/recorder.js` (`REC_VALUE_KEY`, `recLabel`, `SCH_ICONS`, `recAddPick`, `recStepBody`, `recCode`, новые `recEnsureEditor`/`recEnsureSet`)
- Modify: `frontend/js/steptools.js:13` (`ensure_app` во FLEXIBLE-зеркале)
- Modify: `frontend/css/recorder.css` (цвета `if_phone`)
- Modify: `frontend/strings/ru.json`
- Test: `backend/tests/test_addstep_js.py`

**Interfaces:**
- Consumes: шаги и код из Tasks 5–6 (зеркалим codegen в `blockCode`/`recCode`); `apkList()` и `APK_LIB` (Task 9); `appPickHtml/appPickFill`; `PLATFORM_NAMES`; `recApp`.
- Produces: `PHONE_CHECK_FIELDS`, `phoneCheckText(args)`, `blockIfPhoneEditor(step)`, `recPhoneCheck(id, check)`, `PHONE_CARD_ARGS`, `ensureAppLabel(args)`.

- [ ] **Step 1: Тест плана «Добавить шаг»** — в `backend/tests/test_addstep_js.py`:

- строку `assert.deepStrictEqual(keys(p), ['repeat', 'seen', 'chance', 'action', 'other']);` заменить на
  `assert.deepStrictEqual(keys(p), ['repeat', 'seen', 'phone', 'chance', 'action', 'other']);`
- после неё добавить:
```js
assert.deepStrictEqual(items(p, 'phone').map(i => i.key),
    ['phone_app', 'phone_no_app', 'phone_older', 'phone_battery', 'phone_offline', 'phone_space', 'phone_account']);
```
- в блоке «предельная глубина» цикл `for (const k of ['loop', 'until', 'if_seen', 'if_not', 'chance'])` заменить на
  `for (const k of ['loop', 'until', 'if_seen', 'if_not', 'chance', 'phone_app', 'phone_battery'])`;
- в блоке «Выбраны шаги» (`plan({sel: 2, …})`) две проверки заменить на:
```js
assert.deepStrictEqual(keys(p), ['repeat', 'seen', 'phone', 'chance']);
assert.deepStrictEqual(p.groups.flatMap(g => g.items).map(i => i.key),
    ['loop', 'until', 'if_seen', 'if_not', 'phone_app', 'phone_no_app', 'phone_older', 'phone_battery',
     'phone_offline', 'phone_space', 'phone_account', 'chance']);
```
  (выделение можно обернуть и в «Если на телефоне»).

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_addstep_js.py`
Expected: FAIL (группы `phone` нет).

- [ ] **Step 2: `addstep.js`**

В `addStepPlan` после `groups.push({key: 'seen', items: seen});`:

```js
    /* Факты о телефоне — не о экране: своя группа, иначе десять карточек
       «если…» сливаются в стену. Телефон для них не нужен — проверка идёт
       на прогоне. */
    groups.push({key: 'phone', items: ['phone_app', 'phone_no_app', 'phone_older', 'phone_battery',
        'phone_offline', 'phone_space', 'phone_account'].map(k => item(k, deep))});
```

`addStepGroupName`:

```js
function addStepGroupName(key) {
    return key === 'action' ? t('rec.dob_deystvie') : key === 'repeat' ? t('rec.dob_povtoryat')
        : key === 'seen' ? t('rec.dob_esli') : key === 'phone' ? t('rec.dob_telefon')
        : key === 'chance' ? t('rec.dob_inogda') : t('rec.dob_drugoe');
}

const ADD_STEP_GROUP_ICON = {action: 'plus', repeat: 'rotate', seen: 'eye', phone: 'phone', chance: 'dice', other: 'layers'};
```

В `addStepItemText` перед `default:`:

```js
        case 'phone_app': return {icon: 'phone', title: t('rec.dob_tel_app'), desc: t('rec.dob_tel_app_d')};
        case 'phone_no_app': return {icon: 'phone', title: t('rec.dob_tel_no_app'), desc: t('rec.dob_tel_no_app_d')};
        case 'phone_older': return {icon: 'refresh', title: t('rec.dob_tel_older'), desc: t('rec.dob_tel_older_d')};
        case 'phone_battery': return {icon: 'battery', title: t('rec.dob_tel_battery'), desc: t('rec.dob_tel_battery_d')};
        case 'phone_offline': return {icon: 'wifi', title: t('rec.dob_tel_offline'), desc: t('rec.dob_tel_offline_d')};
        case 'phone_space': return {icon: 'download', title: t('rec.dob_tel_space'), desc: t('rec.dob_tel_space_d')};
        case 'phone_account': return {icon: 'shield', title: t('rec.dob_tel_account'), desc: t('rec.dob_tel_account_d')};
```

(`recIcon(id)` рисует `#i-<id>`; `i-phone`, `i-battery`, `i-wifi`, `i-refresh`, `i-download`, `i-shield` в `index.html` уже есть.)

Run: `cd backend && ../.venv/bin/python -m pytest -q tests/test_addstep_js.py` → PASS.

- [ ] **Step 3: Строки** — в `frontend/strings/ru.json` (раздел `rec.`):

```json
  "rec.dob_telefon": "Если на телефоне",
  "rec.dob_tel_app": "Если приложение есть",
  "rec.dob_tel_app_d": "шаги внутри — только если оно установлено",
  "rec.dob_tel_no_app": "Если приложения нет",
  "rec.dob_tel_no_app_d": "например, поставить его из библиотеки",
  "rec.dob_tel_older": "Если версия ниже",
  "rec.dob_tel_older_d": "обновить старое приложение",
  "rec.dob_tel_battery": "Если заряд меньше",
  "rec.dob_tel_battery_d": "например, закончить сценарий",
  "rec.dob_tel_offline": "Если нет интернета",
  "rec.dob_tel_offline_d": "подождать или закончить",
  "rec.dob_tel_space": "Если мало места",
  "rec.dob_tel_space_d": "свободно меньше заданного",
  "rec.dob_tel_account": "Если не привязан аккаунт",
  "rec.dob_tel_account_d": "VK, Instagram, TikTok или Telegram",
  "rec.tel_c_app": "Приложение установлено",
  "rec.tel_c_older": "Версия приложения ниже",
  "rec.tel_c_battery": "Заряд меньше",
  "rec.tel_c_offline": "Нет интернета",
  "rec.tel_c_space": "Мало места",
  "rec.tel_c_account": "Не привязан аккаунт",
  "rec.tel_prilozhenie": "приложение",
  "rec.tel_est_prilozhenie": "Если на телефоне есть {app}",
  "rec.tel_net_prilozheniya": "Если на телефоне нет {app}",
  "rec.tel_versiya_nizhe": "Если версия {app} ниже {v}",
  "rec.tel_versiya_ne_nizhe": "Если версия {app} не ниже {v}",
  "rec.tel_zaryad_menshe": "Если заряд меньше {n}%",
  "rec.tel_zaryad_ne_menshe": "Если заряд не меньше {n}%",
  "rec.tel_net_interneta": "Если нет интернета",
  "rec.tel_est_internet": "Если есть интернет",
  "rec.tel_malo_mesta": "Если свободно меньше {n} ГБ",
  "rec.tel_mesta_hvataet": "Если свободно не меньше {n} ГБ",
  "rec.tel_net_akkaunta": "Если к телефону не привязан аккаунт {p}",
  "rec.tel_akkaunt_est": "Если к телефону привязан аккаунт {p}",
  "rec.tel_kakoe": "Приложение",
  "rec.tel_versiya": "Версия",
  "rec.tel_zaryad": "Заряд",
  "rec.tel_mesto": "Свободно",
  "rec.tel_gb": "ГБ",
  "rec.tel_akkaunt": "Аккаунт",
  "rec.gotov_postavit": "{app} готов, иначе поставить",
  "rec.gotov_postavit_v": "{app} не ниже {v}, иначе поставить",
  "rec.gotov_proverka": "Проверить, что {app} установлен",
  "rec.gotov_proverka_v": "Проверить, что {app} не ниже {v}",
  "rec.gotov_ne_nizhe": "Версия не ниже",
  "rec.gotov_lyubaya": "любая",
  "rec.gotov_stavit": "Если нет или старое — поставить из библиотеки",
  "rec.gotov_v_bib": "в библиотеке {v}",
  "rec.gotov_net_v_bib": "нет в библиотеке — шаг только проверит, пока не добавите APK в Сценарии → Приложения"
```

- [ ] **Step 4: `blocks.js`**

`BLOCK_KINDS` — добавить:

```js
    if_phone: {icon: 'phone', defaults: () => ({check: 'app_installed', negate: false})},
```

и под `UNTIL_FEATS`:

```js
/* Поля каждой проверки «если на телефоне» — как steps.PHONE_CHECKS. */
const PHONE_CHECK_FIELDS = {
    app_installed: ['package'], app_older: ['package', 'version'], battery_below: ['percent'],
    offline: [], space_below: ['gb'], no_account: ['platform'],
};

function phoneCheckName(c) {
    return c === 'app_installed' ? t('rec.tel_c_app') : c === 'app_older' ? t('rec.tel_c_older')
        : c === 'battery_below' ? t('rec.tel_c_battery') : c === 'offline' ? t('rec.tel_c_offline')
        : c === 'space_below' ? t('rec.tel_c_space') : t('rec.tel_c_account');
}

function phoneCheckText(a) {
    const app = a.package ? recApp(a.package) : t('rec.tel_prilozhenie');
    const p = PLATFORM_NAMES[a.platform] || a.platform || '';
    switch (a.check) {
        case 'app_installed':
            return a.negate ? t('rec.tel_net_prilozheniya', {app}) : t('rec.tel_est_prilozhenie', {app});
        case 'app_older':
            return a.negate ? t('rec.tel_versiya_ne_nizhe', {app, v: a.version || '?'})
                : t('rec.tel_versiya_nizhe', {app, v: a.version || '?'});
        case 'battery_below':
            return a.negate ? t('rec.tel_zaryad_ne_menshe', {n: a.percent}) : t('rec.tel_zaryad_menshe', {n: a.percent});
        case 'offline':
            return a.negate ? t('rec.tel_est_internet') : t('rec.tel_net_interneta');
        case 'space_below':
            return a.negate ? t('rec.tel_mesta_hvataet', {n: recNum(a.gb)}) : t('rec.tel_malo_mesta', {n: recNum(a.gb)});
        default:
            return a.negate ? t('rec.tel_akkaunt_est', {p}) : t('rec.tel_net_akkaunta', {p});
    }
}
```

`blockPayloadArgs` — ветка после `if_seen`:

```js
    } else if (step.kind === 'if_phone') {
        out.check = a.check;
        out.negate = !!a.negate;
        for (const f of PHONE_CHECK_FIELDS[a.check] || []) {
            out[f] = f === 'percent' || f === 'gb' ? Number(a[f]) : String(a[f] ?? '');
        }
    }
```

`blockLabel` — первой строкой функции:

```js
    if (step.kind === 'if_phone') return phoneCheckText(step.args);
```

`blockCode` — после `if (step.kind === 'chance') …`:

```js
    if (step.kind === 'if_phone') {
        const parts = [JSON.stringify(a.check)];
        for (const f of ['package', 'version', 'platform']) if (a[f] != null) parts.push(`${f}=${JSON.stringify(a[f])}`);
        for (const f of ['percent', 'gb']) if (a[f] != null) parts.push(`${f}=${recNum(a[f])}`);
        return `if ${a.negate ? 'not ' : ''}ctx.phone_is(${parts.join(', ')}):`;
    }
```

`recBlockEditor` — выбор редактора:

```js
    const body = step.kind === 'loop' ? blockLoopEditor(step)
        : step.kind === 'chance' ? blockChanceEditor(step)
        : step.kind === 'if_seen' ? blockIfSeenEditor(step)
        : step.kind === 'if_phone' ? blockIfPhoneEditor(step) : blockUntilEditor(step);
```

После `blockIfSeenEditor`:

```js
function blockIfPhoneEditor(step) {
    const a = step.args;
    const fields = PHONE_CHECK_FIELDS[a.check] || [];
    const row = (label, html) => `<div class="blk-ed-row"><span class="blk-ed-k">${esc(label)}</span>${html}</div>`;
    const chip = neg => `<button class="chip ${!!a.negate === neg ? 'on' : ''}" aria-pressed="${!!a.negate === neg}"
        onclick="recBlockSet(${step.id}, 'negate', ${neg})">${esc(phoneCheckText(Object.assign({}, a, {negate: neg})))}</button>`;
    const pid = 'phoneApp' + step.id;
    if (fields.includes('package')) setTimeout(() => appPickFill(pid), 0);
    const checks = Object.keys(PHONE_CHECK_FIELDS).map(c =>
        `<option value="${c}" ${a.check === c ? 'selected' : ''}>${esc(phoneCheckName(c))}</option>`).join('');
    const platforms = Object.keys(PLATFORM_NAMES).map(p =>
        `<option value="${p}" ${a.platform === p ? 'selected' : ''}>${esc(PLATFORM_NAMES[p])}</option>`).join('');
    return row(t('rec.uslovie'), `<select aria-label="${esc(t('rec.uslovie'))}"
            onchange="recPhoneCheck(${step.id}, this.value)">${checks}</select>`)
        + `<div class="blk-ed-row"><div class="chips" role="group">${chip(false)}${chip(true)}</div></div>`
        + (fields.includes('package') ? row(t('rec.tel_kakoe'),
            appPickHtml(pid, a.package, v => recBlockSet(step.id, 'package', v))) : '')
        + (fields.includes('version') ? row(t('rec.tel_versiya'), `<input type="text" class="blk-ed-n" placeholder="8.40"
            aria-label="${esc(t('rec.tel_versiya'))}" value="${esc(a.version || '')}"
            onchange="recBlockSet(${step.id}, 'version', this.value.trim())">`) : '')
        + (fields.includes('percent') ? row(t('rec.tel_zaryad'), `<input type="number" class="blk-ed-n" min="1" max="99"
            aria-label="${esc(t('rec.tel_zaryad'))}" value="${a.percent ?? 20}"
            onchange="recBlockSet(${step.id}, 'percent', this.value)"><span>%</span>`) : '')
        + (fields.includes('gb') ? row(t('rec.tel_mesto'), `<input type="number" class="blk-ed-n" min="0.1" max="256" step="0.5"
            aria-label="${esc(t('rec.tel_mesto'))}" value="${a.gb ?? 1}"
            onchange="recBlockSet(${step.id}, 'gb', this.value)"><span>${esc(t('rec.tel_gb'))}</span>`) : '')
        + (fields.includes('platform') ? row(t('rec.tel_akkaunt'), `<select aria-label="${esc(t('rec.tel_akkaunt'))}"
            onchange="recBlockSet(${step.id}, 'platform', this.value)">${platforms}</select>`) : '')
        + `<div class="blk-ed-row"><span class="sp"></span>
            <button class="sm ghost" onclick="recIfSeenElse(${step.id})"
                    title="${esc(t('rec.inache_podskazka'))}">${esc(t('rec.dobavit_inache'))}</button></div>`;
}

/* Сменили проверку — поля прежней убираем, новой ставим значения по умолчанию. */
function recPhoneCheck(id, check) {
    const step = recFind(id);
    if (!step || !PHONE_CHECK_FIELDS[check]) return;
    const keep = {package: step.args.package || '', version: step.args.version || '',
        percent: step.args.percent ?? 20, gb: step.args.gb ?? 1, platform: step.args.platform || 'vk'};
    step.args = {check, negate: !!step.args.negate};
    for (const f of PHONE_CHECK_FIELDS[check]) step.args[f] = keep[f];
    recRender();
    recSave();
}
```

`recBlockSet` — перед финальным `else {`:

```js
    } else if (['package', 'version', 'platform'].includes(field)) {
        a[field] = String(value || '');
    } else if (field === 'percent' && step.kind === 'if_phone') {
        a.percent = Math.min(99, Math.max(1, Math.round(Number(value) || 1)));
```

(вставить эту ветку **до** существующей `else if (field === 'percent')`, иначе сработает ограничение «с шансом» 1–100.)

`recIfSeenElse` — заменить начало и `other`:

```js
function recIfSeenElse(id) {
    const head = recFind(id);
    if (!head || (head.kind !== 'if_seen' && head.kind !== 'if_phone')) return;
    const at = REC.steps.indexOf(head) + blockOf(head).length;
    const other = head.kind === 'if_seen'
        ? {id: REC.nextId++, kind: 'if_seen', parent: head.parent ?? null,
            args: {negate: !head.args.negate, timeout: head.args.timeout ?? 3},
            any: [...(head.any || [])], param: null, note: '', warn: ''}
        : {id: REC.nextId++, kind: 'if_phone', parent: head.parent ?? null,
            args: Object.assign({}, head.args, {negate: !head.args.negate}),
            param: null, note: '', warn: ''};
```

(остаток функции — пауза-заготовка, `splice`, `recRender`, `recSave`, тост — без изменений).

Граф: строку `if (head.kind === 'chance' || head.kind === 'if_seen' || block.length < 2) return;` заменить на
`if (head.kind === 'chance' || head.kind === 'if_seen' || head.kind === 'if_phone' || block.length < 2) return;`

- [ ] **Step 5: `recorder.js`**

`REC_VALUE_KEY` — добавить `ensure_app: 'package',`.

`SCH_ICONS` — добавить `if_phone: ['until', 'phone'], ensure_app: ['block', 'phone'],`.

`recLabel` — в группу `case 'loop': case 'chance': case 'until': case 'if_seen':` добавить `case 'if_phone':`; перед `case 'break':`:

```js
        case 'ensure_app':
            return ensureAppLabel(a);
```

рядом с `recLabel`:

```js
function ensureAppLabel(a) {
    const app = recApp(a.package);
    if (a.install === false) {
        return a.min_version ? t('rec.gotov_proverka_v', {app, v: a.min_version}) : t('rec.gotov_proverka', {app});
    }
    return a.min_version ? t('rec.gotov_postavit_v', {app, v: a.min_version}) : t('rec.gotov_postavit', {app});
}
```

`recAddPick` — первой веткой после `anchor`:

```js
    if (PHONE_CARD_ARGS[key]) {
        if (REC.sel && REC.sel.size) recSelBlock('if_phone');
        else recBlockNew('if_phone');
        const head = recFind(REC.open);
        if (head && head.kind === 'if_phone') {
            head.args = Object.assign({}, PHONE_CARD_ARGS[key]);
            recRender();
            recSave();
        }
        closeModal();
        return;
    }
```

и над `recAddPick`:

```js
/* Карточки «Если на телефоне» → готовые аргументы блока. Приложение
   выбирают в открывшемся блоке: без него сохранение подскажет, чего нет. */
const PHONE_CARD_ARGS = {
    phone_app: {check: 'app_installed', negate: false, package: ''},
    phone_no_app: {check: 'app_installed', negate: true, package: ''},
    phone_older: {check: 'app_older', negate: false, package: '', version: ''},
    phone_battery: {check: 'battery_below', negate: false, percent: 20},
    phone_offline: {check: 'offline', negate: false},
    phone_space: {check: 'space_below', negate: false, gb: 1},
    phone_account: {check: 'no_account', negate: false, platform: 'vk'},
};
```

`recStepBody` — в `main` после `recValueEditor(step)` добавить `+ recEnsureEditor(step)`; рядом с `recValueEditorPlain`:

```js
/* «Приложение готово»: версия и «ставить ли». Нет в библиотеке — говорим
   об этом прямо под галочкой, а не выключаем её молча. */
function recEnsureEditor(step) {
    if (step.kind !== 'ensure_app') return '';
    const a = step.args;
    if (!APK_LIB.list) apkList().then(() => { if (REC.open === step.id) recRender(); }).catch(() => {});
    const lib = (APK_LIB.list || []).find(x => x.package === a.package);
    const note = lib ? t('rec.gotov_v_bib', {v: lib.version_name}) : t('rec.gotov_net_v_bib');
    return `<div class="row"><label for="ensVer${step.id}">${esc(t('rec.gotov_ne_nizhe'))}</label>
        <input type="text" id="ensVer${step.id}" class="grow" placeholder="${esc(t('rec.gotov_lyubaya'))}"
               value="${esc(a.min_version || '')}" oninput="recEnsureSet(${step.id}, 'min_version', this.value.trim())">
      </div>
      <label class="inline-check"><input type="checkbox" ${a.install !== false ? 'checked' : ''}
             onchange="recEnsureSet(${step.id}, 'install', this.checked)">
        <span>${esc(t('rec.gotov_stavit'))}<small>${esc(note)}</small></span></label>`;
}

function recEnsureSet(id, key, value) {
    const step = recFind(id);
    if (!step) return;
    if (key === 'min_version' && !value) delete step.args.min_version;
    else step.args[key] = value;
    recSave();
}
```

`recCode` — перед общей веткой значений (`return \`ctx.${step.kind}(${value})\``):

```js
    if (step.kind === 'ensure_app') {
        const parts = [step.param ? `ctx.params[${JSON.stringify(step.param)}]` : JSON.stringify(a.package)];
        if (a.min_version) parts.push(`min_version=${JSON.stringify(a.min_version)}`);
        if (a.install === false) parts.push('install=False');
        return `ctx.ensure_app(${parts.join(', ')})`;
    }
```

- [ ] **Step 6: `steptools.js:13`** — в множество шагов «можно пропустить/повторить» добавить `'ensure_app'`.

- [ ] **Step 7: Цвета блока** — в `frontend/css/recorder.css` рядом с правилами `if_seen` (строки ~858, ~883, ~963):

```css
.rs-block-if_phone, .rs-in-if_phone { --blk: var(--line-hover); --blk-dim: var(--panel2); }
.rs.rs-block.rs-block-if_phone { --blk: var(--line-hover); --blk-dim: var(--panel2); }
.gr-block-if_phone { --blk-c: var(--line-hover); }
```

- [ ] **Step 8: Проверки**

Run:
```bash
for f in blocks addstep recorder steptools apppick apklib; do node --check frontend/js/$f.js || echo FAIL $f; done
cd backend && ../.venv/bin/python -m pytest -q tests/test_addstep_js.py tests/test_strings.py tests/test_repair_js.py
```
Expected: без `FAIL`, тесты зелёные.

- [ ] **Step 9: Коммит**

```bash
git add frontend/js/blocks.js frontend/js/addstep.js frontend/js/recorder.js frontend/js/steptools.js frontend/css/recorder.css frontend/strings/ru.json backend/tests/test_addstep_js.py
git commit -m "Конструктор: блок «Если на телефоне» и шаг «Приложение готово»

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Документация, полный прогон, проверка в браузере

**Files:**
- Modify: `docs/recipe-format.md` (разделы `if_phone`, `ensure_app`)
- Modify: `docs/superpowers/specs/2026-10-19-phone-checks-design.md` (раздел «Отступления при планировании» — шесть пунктов из шапки плана)
- Modify: `.claude/skills/farm-ux/SKILL.md` (LaiXi-список: «проверки телефона в сценарии и библиотека APK»; строка про `if_phone` в правилах блоков)

- [ ] **Step 1: `docs/recipe-format.md`** — после описания `if_seen` добавить:

````markdown
### `if_phone` — «Если на телефоне»

Блок: следующие `span` шагов выполняются, только если факт о телефоне верен
(с `negate: true` — если неверен). «Иначе» — такой же блок с обратным `negate`.

| `check` | Поля | Верно, когда |
|---|---|---|
| `app_installed` | `package` | приложение установлено |
| `app_older` | `package`, `version` | версия ниже `version` (или приложения нет) |
| `battery_below` | `percent` (1–99) | заряд меньше |
| `offline` | — | нет интернета |
| `space_below` | `gb` (0.1–256) | свободно меньше |
| `no_account` | `platform` (`vk`/`inst`/`tiktok`/`tg`) | аккаунт не привязан |

```json
{"kind": "if_phone", "args": {"span": 1, "check": "battery_below", "percent": 20}}
```

### `ensure_app` — «Приложение готово»

Установлено и не старее `min_version`; нет — ставится из библиотеки APK
(Сценарии → Приложения). `install: false` — только проверить.

```json
{"kind": "ensure_app", "args": {"package": "com.vkontakte.android", "min_version": "8.40"}}
```
````

- [ ] **Step 2: Спека и скилл** — дописать в спеку раздел `## 6. Отступления при планировании` с шестью пунктами из шапки этого плана; в `farm-ux/SKILL.md` в «LaiXi parity checklist» → Done дописать «проверки телефона в сценарии (`if_phone`), шаг «Приложение готово» (`ensure_app`), библиотека APK (Сценарии → Приложения)»; в правила конструктора — строку: «`if_phone` 📱 — факт о телефоне, цвет как у `if_seen`; поля по `PHONE_CHECK_FIELDS`; «+ иначе» — двойник с обратным `negate`».

- [ ] **Step 3: Полный прогон**

Run: `cd backend && ../.venv/bin/python -m pytest -q`
Expected: всё зелёное (было 1117 passed, 6 skipped + новые).

- [ ] **Step 4: Браузер — один раз, 1280 и 1728**

Перезапустить ферму (`./run.sh`), жёсткая перезагрузка страницы. Проверить:
1. Сценарии → «Приложения»: пустое состояние; перетащить `.apk` (любой настоящий) → строка «VK · версия … · … МБ»; «Переименовать»; «Удалить» — два клика.
2. Конструктор → «Добавить шаг»: группа «Если на телефоне», семь карточек; «Если заряд меньше» → блок с подписью «Если заряд меньше 20%», «+ иначе» добавляет «Если заряд не меньше 20%».
3. «Действие» → «Приложение готово» → приложение из библиотеки в списке выбора, даже если его нет на телефоне; подпись шага ««VK» готов, иначе поставить».
4. ▶ на блоке и на шаге на живом телефоне — в журнале строка «на телефоне: …».
5. 1280 и 1728: нет переносов в панели и переполнений в редакторе блока.

LocalStorage пользователя не чистить (черновики `farm.recorder.draft.*`).

- [ ] **Step 5: Коммит**

```bash
git add docs/recipe-format.md docs/superpowers/specs/2026-10-19-phone-checks-design.md .claude/skills/farm-ux/SKILL.md
git commit -m "Документация: проверки телефона и библиотека APK

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
