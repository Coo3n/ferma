"""Запись сгенерированного сценария в папку scenarios/."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import threading
from pathlib import Path

from .. import config, scenarios
from . import codegen

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class SaveError(ValueError):
    """Некорректный ключ, путь вне папки или пустая запись — 400."""


class Conflict(ValueError):
    """Файл уже существует, перезапись не разрешена — 409."""


class SaveIOError(SaveError, OSError):
    """Сбой диска при публикации/подготовке — 500, не вина запроса.

    rolled_back: удалось ли вернуть файлы в прежнее состояние. От этого
    зависит, что можно сказать пользователю: «ничего не изменено» или «состояние
    неопределённо, сохраните ещё раз».
    """

    # ещё и OSError: вызывающие, что ловили сбой диска как OSError, не ломаются
    def __init__(self, message, rolled_back: bool):
        super().__init__(message)
        self.rolled_back = rolled_back


class NotRecorded(Conflict, SaveError):
    """Существующий файл написан вручную: конструктор его не трогает — 409."""


# Два save() одного ключа не должны перемежаться: у каждого свои временные
# файлы и своя очистка «лишних» кропов, вместе они собрали бы смесь двух версий.
# Замок на ПРОЦЕСС: предполагается один воркер uvicorn (несколько процессов
# эту защиту не разделят). На Windows os.replace может упасть PermissionError,
# если файл открыт другой программой — это тот же OSError и уходит в откат.
_lock = threading.Lock()


def target_path(key) -> Path:
    """Путь файла сценария. Ключ проверяется дважды намеренно.

    Регулярка уже запрещает точки и слеши, но проверка `is_relative_to`
    остаётся: она не даст выйти за папку, даже если правило когда-нибудь
    ослабят. Нижний регистр и запрет ведущего `_` не косметика — `discover()`
    пропускает файлы, начинающиеся с подчёркивания.
    """
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise SaveError(
            "имя файла: латиница в нижнем регистре, цифры и _, начиная с буквы")
    root = Path(config.SCENARIOS_DIR).resolve()
    path = (root / f"{key}.py").resolve()
    if not path.is_relative_to(root):
        raise SaveError("путь вне папки сценариев")
    return path


ASSET_RE = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,60}\.png$")

# Рецепт — шаги в том виде, в каком их прислал конструктор. Сгенерированный
# .py разобрать назад нельзя (это односторонняя сборка), а править записанный
# сценарий нужно: без рецепта единственный способ поменять один шаг — писать
# весь сценарий заново. Лежит в папке ассетов, а не рядом с .py, чтобы
# scenarios/ оставалась папкой сценариев, и чтобы удаление сценария уносило
# рецепт тем же delete_assets().
RECIPE = "recipe.json"

MAX_ASSETS = 60
MAX_ASSET_BYTES = 300_000  # кроп кнопки; полноэкранный снимок сюда не влезет — и не должен


def assets_dir(key) -> Path:
    """Папка ассетов сценария; ключ проверяется так же, как в target_path."""
    path = target_path(key)
    return path.with_name(f"{path.stem}_assets")


def recipe_path(key) -> Path:
    """Путь рецепта; ключ проверяется так же, как в target_path."""
    return assets_dir(key) / RECIPE


def has_recipe(key) -> bool:
    """Есть ли чем открыть сценарий на правку. Без чтения файла: список
    сценариев спрашивает это про каждый сценарий сразу."""
    try:
        return recipe_path(key).is_file()
    except SaveError:
        return False


def load_recipe(key) -> dict | None:
    """Рецепт сценария или None, если его нет (сценарий не из конструктора,
    либо записан версией фермы, которая рецептов ещё не писала)."""
    try:
        path = recipe_path(key)
    except SaveError:
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_line_map(key) -> dict[int, int]:
    """Карта «строка .py → индекс шага» с int-ключами; {} у старых рецептов."""
    raw = (load_recipe(key) or {}).get("line_map")
    if not isinstance(raw, dict):
        return {}
    try:
        return {int(k): int(v) for k, v in raw.items()}
    except (TypeError, ValueError):
        return {}


def load_assets(key) -> dict:
    """Кропы сценария в base64 — конструктор правит их вместе со шагами."""
    try:
        directory = assets_dir(key)
    except SaveError:
        return {}
    out = {}
    for path in sorted(directory.glob("*.png")):
        if not ASSET_RE.match(path.name):
            continue
        try:
            out[path.name] = base64.b64encode(path.read_bytes()).decode()
        except OSError:
            continue
    return out


def delete(key, path: Path | None = None) -> None:
    """Снести .py и папку ассетов под одним замком.

    Порознь (unlink вне замка, потом delete_assets) параллельный save между
    ними воскресил бы .py без рецепта и кропов. Негодный ключ — не ошибка.
    """
    with _lock:
        try:
            target = path or target_path(key)
        except SaveError:
            target = None
        if target is not None:
            target.unlink(missing_ok=True)
        try:
            shutil.rmtree(assets_dir(key), ignore_errors=True)
        except SaveError:
            pass
        scenarios.invalidate(key)


def delete_assets(key) -> None:
    """Снести папку ассетов. Негодный ключ и отсутствие папки — не ошибка:
    удаление вызывается из эндпоинта, который уже отработал по .py-файлу."""
    with _lock:
        try:
            shutil.rmtree(assets_dir(key), ignore_errors=True)
        except SaveError:
            pass


def load_code_sha256(key) -> str:
    """sha256 байтов .py, с которыми был записан рецепт; "" если его нет.

    line_map верен только для того кода, что писался вместе с ним. Читающий
    сверяет этот хэш с хэшем байтов файла: несовпадение — файл менялся мимо
    конструктора или запись прервалась между .py и рецептом, карте строк
    верить нельзя. У старых рецептов ключа нет — они остаются рабочими, просто
    без сопоставления строки и шага, пока их не пересохранят.
    """
    value = (load_recipe(key) or {}).get("code_sha256")
    return value if isinstance(value, str) else ""


def _decode_assets(assets) -> dict:
    """Проверить и раскодировать кропы. Ничего не пишет на диск."""
    if not assets:
        return {}
    if not isinstance(assets, dict):
        raise SaveError("assets: ожидается объект {имя_файла: base64}")
    if len(assets) > MAX_ASSETS:
        raise SaveError(f"слишком много ассетов: {len(assets)} > {MAX_ASSETS}")
    decoded = {}
    for name, b64 in assets.items():
        if not isinstance(name, str) or not ASSET_RE.match(name):
            raise SaveError(f"имя ассета «{name}»: png из латиницы, цифр, _ . -")
        try:
            data = base64.b64decode(b64, validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise SaveError(f"ассет «{name}»: не base64")
        if len(data) > MAX_ASSET_BYTES:
            raise SaveError(f"ассет «{name}» больше {MAX_ASSET_BYTES} байт")
        decoded[name] = data
    return decoded


def _width(raw) -> int | None:
    """Ширина экрана: None/0/"" — не задана, иначе конечное положительное целое.
    Проверяется до замка и до диска: int("abc") иначе стал бы 500 посреди записи."""
    if raw is None or raw == 0 or raw == "":
        return None
    try:
        if isinstance(raw, bool):
            raise TypeError
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        raise SaveError("screen_width: ожидается положительное целое число")
    if value <= 0:
        raise SaveError("screen_width: ожидается положительное целое число")
    return value


def _recipe_bytes(meta, params, steps, screen_width, line_map, code_sha256) -> bytes:
    return json.dumps({
        "meta": meta,
        "params": params,
        "steps": steps,
        "screen_width": screen_width,
        # строка .py → индекс шага; ключи в JSON строковые, читать через
        # load_line_map. У рецептов старых версий ключа нет.
        "line_map": line_map or {},
        # sha256 байтов .py; см. load_code_sha256
        "code_sha256": code_sha256,
    }, ensure_ascii=False, indent=1).encode("utf-8")


def _tmp(path: Path) -> Path:
    # не *.png и не *.py: ни загрузчик сценариев, ни load_assets не увидят
    return path.with_name(f".{path.name}.tmp")


def _snapshot(paths) -> dict:
    """Текущее содержимое файлов (None — файла нет) для отката.

    «Нет» — только FileNotFoundError. Нечитаемый файл, записанный как «нет»,
    откат потом удалил бы: терять то, что не смогли даже прочитать, нельзя.
    """
    out = {}
    for p in paths:
        try:
            out[p] = p.read_bytes()
        except FileNotFoundError:
            out[p] = None
        except OSError as e:
            raise SaveIOError(
                f"не удалось прочитать «{p.name}»: {e.strerror or e}", rolled_back=True)
    return out


def _restore(snap: dict, touched) -> bool:
    """Вернуть только те файлы, что публикация успела тронуть.
    True — всё вернулось; best effort, но собственный .tmp не оставляем."""
    ok = True
    for p in touched:
        data = snap[p]
        t = _tmp(p)
        try:
            if data is None:
                p.unlink(missing_ok=True)
            else:
                t.write_bytes(data)
                os.replace(t, p)
        except OSError:
            ok = False
            try:
                t.unlink(missing_ok=True)
            except OSError:
                pass
    return ok


def _fsync(path: Path) -> None:
    """Сбросить файл на диск до os.replace: иначе после потери питания
    переименованный файл может оказаться пустым. Каталог не синхронизируем."""
    with open(path, "rb+") as f:
        os.fsync(f.fileno())


def save(key, meta: dict, params: dict, steps: list, overwrite: bool = False,
         assets: dict | None = None, screen_width: int | None = None) -> Path:
    """Записать сценарий, не оставляя половинчатого состояния.

    Порядок: 1) ВСЁ проверяем (шаги, ключ, кропы, компиляция кода) — до
    первого касания диска, поэтому отказ 400 не стоит пользователю ни одного
    файла; 2) все файлы пишутся во временные рядом с целевыми; 3) публикация
    через os.replace: png → meta.json → .py → recipe.json; 4) лишние старые
    png сносятся уже после. Окно между .py и recipe.json безвредно: рецепт
    хранит sha256 кода, читающий видит несовпадение и не верит старому
    line_map, а следующее сохранение перепишет оба файла. Сбой публикации
    откатывает уже заменённые файлы из снимка.
    """
    if not steps:
        raise SaveError("нет ни одного шага")
    path = target_path(key)
    screen_width = _width(screen_width)
    decoded = _decode_assets(assets)
    code, line_map = codegen.render_mapped(meta, params, steps)
    try:
        # страховка: любой строковый литерал, что кодоген пропустил сырым,
        # иначе убил бы сценарий на всех устройствах при следующем discover
        compile(code, str(path), "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as e:
        raise SaveError(f"сгенерированный код не компилируется: {e}")
    try:
        code_bytes = code.encode("utf-8")  # байты, а не текст: хэш = файл на любой ОС
    except UnicodeEncodeError:
        raise SaveError("текст содержит недопустимые символы (одиночные суррогаты)")

    with _lock:
        if path.exists():
            if not overwrite:
                raise Conflict(f"сценарий «{key}» уже существует")
            if not scenarios.is_recorded(path):
                raise NotRecorded(
                    f"файл «{key}.py» написан вручную, конструктор его не перезапишет")
        directory = assets_dir(key)

        recipe_file = directory / RECIPE
        meta_file = directory / "meta.json"
        # (итоговый путь, байты) в порядке публикации
        plan = [(directory / name, data) for name, data in decoded.items()]
        if screen_width:
            plan.append((meta_file, json.dumps(
                {"screen_width": screen_width}).encode("utf-8")))
        plan.append((path, code_bytes))
        plan.append((recipe_file, _recipe_bytes(
            meta, params, steps, screen_width, line_map,
            hashlib.sha256(code_bytes).hexdigest())))

        stale = [p for p in directory.glob("*.png")
                 if ASSET_RE.match(p.name) and p.name not in decoded]
        targets = [p for p, _ in plan]
        drop_meta = not screen_width and meta_file.exists()
        snap = _snapshot(targets + stale + ([meta_file] if drop_meta else []))
        tmps, touched = [], []
        made_dir = not directory.exists()   # пустую папку неудачной первой записи уберём
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            for target, data in plan:
                t = _tmp(target)
                tmps.append(t)
                t.write_bytes(data)
                if target in (path, recipe_file):
                    _fsync(t)
            for target, _ in plan:
                os.replace(_tmp(target), target)
                touched.append(target)
                if target == path:
                    # не полагаться на mtime: следующий прогон возьмёт новый код
                    scenarios.invalidate(key)
            for p in stale:
                p.unlink(missing_ok=True)
                touched.append(p)
            if drop_meta:
                meta_file.unlink(missing_ok=True)
                touched.append(meta_file)
        except BaseException as exc:
            rolled = False
            try:
                for t in tmps:
                    try:
                        t.unlink(missing_ok=True)
                    except OSError:
                        pass  # уборка не должна мешать откату ниже
            finally:
                # откат обязан выполниться при любом исходе уборки
                rolled = _restore(snap, touched)
                if made_dir:
                    try:
                        directory.rmdir()   # только пустую
                    except OSError:
                        pass
                scenarios.invalidate(key)
            if isinstance(exc, OSError):
                raise SaveIOError(f"сбой записи на диск: {exc.strerror or exc}",
                                  rolled_back=rolled) from exc
            raise
    return path
