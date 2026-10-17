#!/usr/bin/env python3
"""Демо починки шага без телефона: панель на временных каталогах с готовыми
отклонениями.

    python3 tools/seed_repair_demo.py [--port 8777]

Каталоги сценариев/артефактов/сети/стражей — временные, настоящие scenarios/,
artifacts/, network.json, devices.json не трогаются. Журнал отклонений живёт
в памяти процесса, поэтому засев и сервер — один процесс.

Порядок важен: farm.config читает окружение при импорте, так что переменные
ставятся ДО первого `import farm.*`. Импорты farm — внутри функций.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
W, H = 1080, 2400
JOB_ID = "job000000001"
KEY = "demo_login"
KEY_MANUAL = "demo_manual"

# Нарисованные «элементы экрана»: (id, текст, рамка в пикселях, кликабельно).
# Те же рамки уходят в XML-дамп, так что рамка на скрине = узел в дереве.
ELEMENTS = [
    ("title", "Добро пожаловать", (140, 300, 940, 420), False),
    ("phone", "Номер телефона", (100, 700, 980, 860), False),
    ("login", "Войти", (100, 1700, 980, 1900), True),
    ("forgot", "Забыли пароль?", (300, 2020, 780, 2100), True),
]

MANUAL_SCENARIO = '''"""Демо: сценарий, написанный руками (без рецепта) — починить кликом нельзя."""
NAME = "Демо: ручной сценарий"
DESCRIPTION = "Есть только .py, рецепта нет — у отклонения не будет кнопки починки"


def run(ctx):
    ctx.launch_app("com.example.demo", stop_first=True)
    ctx.click(text="Войти")
'''

FONTS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
         "/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "C:/Windows/Fonts/arial.ttf"]


def _font(size):
    from PIL import ImageFont
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()   # без кириллицы: подписи станут «квадратиками»


def draw_screen():
    """Портретный «экран телефона» W×H, ужатый до ARTIFACT_MAX_WIDTH, как настоящий."""
    import io
    from PIL import Image, ImageDraw
    from farm import config
    img = Image.new("RGB", (W, H), (245, 246, 250))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 110), fill=(30, 40, 70))            # статус-бар
    for _id, text, (x1, y1, x2, y2), clickable in ELEMENTS:
        if _id == "login":
            d.rounded_rectangle((x1, y1, x2, y2), 40, fill=(40, 110, 240))
            color, size = (255, 255, 255), 72
        elif _id == "phone":
            d.rounded_rectangle((x1, y1, x2, y2), 24, fill=(255, 255, 255),
                                outline=(150, 156, 170), width=4)
            color, size = (120, 126, 140), 56
        elif _id == "forgot":
            color, size = (40, 110, 240), 52
        else:
            color, size = (30, 40, 70), 80
        font = _font(size)
        box = d.textbbox((0, 0), text, font=font)
        tx = x1 + (x2 - x1 - (box[2] - box[0])) / 2 if _id != "phone" else x1 + 36
        ty = y1 + (y2 - y1 - (box[3] - box[1])) / 2 - box[1]
        d.text((tx, ty), text, fill=color, font=font)
    if img.width > config.ARTIFACT_MAX_WIDTH:
        ratio = config.ARTIFACT_MAX_WIDTH / img.width
        img = img.resize((config.ARTIFACT_MAX_WIDTH, int(img.height * ratio)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def hierarchy_xml():
    """Настоящий uiautomator-дамп: рамки узлов совпадают с нарисованными."""
    nodes = []
    for i, (_id, text, (x1, y1, x2, y2), clickable) in enumerate(ELEMENTS):
        cls = "android.widget.Button" if _id == "login" else (
            "android.widget.EditText" if _id == "phone" else "android.widget.TextView")
        nodes.append(
            f'<node index="{i}" text="{text}" resource-id="com.example.demo:id/{_id}" '
            f'class="{cls}" package="com.example.demo" content-desc="" '
            f'clickable="{"true" if clickable else "false"}" enabled="true" '
            f'bounds="[{x1},{y1}][{x2},{y2}]"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<hierarchy rotation="0"><node index="0" text="" resource-id="" '
            f'class="android.widget.FrameLayout" package="com.example.demo" '
            f'content-desc="" clickable="false" enabled="true" bounds="[0,0][{W},{H}]">'
            + "".join(nodes) + "</node></hierarchy>")


def seed(tmp_dir) -> dict:
    """Кладёт сценарии, артефакты и отклонения. config уже должен смотреть в tmp_dir
    (main ставит окружение до импорта; тест — monkeypatch): так засев не может
    случайно записать в настоящие каталоги."""
    from farm import config, deviations as dv, scenarios, ui as uitree
    from farm.recorder import save, steps

    tmp = Path(tmp_dir)
    if (Path(config.SCENARIOS_DIR) != tmp / "scenarios"
            or Path(config.ARTIFACTS_DIR) != tmp / "artifacts"):
        raise RuntimeError("config смотрит не во временный каталог — засев отменён")
    Path(config.SCENARIOS_DIR).mkdir(parents=True, exist_ok=True)

    recipe = [
        steps.normalize_step({"kind": "sleep", "args": {"seconds": 1}}),
        steps.normalize_step({
            "kind": "click", "selector": {"call": "click", "args": 'text="Войти"'},
            "texts": ["Войти"], "point": [0.5, 0.8]}),
        steps.normalize_step({"kind": "expect", "args": {"name": "home"},
                              "any": ['text="Главная"']}),
    ]
    save.save(KEY, {"name": "Демо: вход", "description": "Записанный сценарий для демо починки",
                    "watch_popups": False}, {}, recipe)
    (Path(config.SCENARIOS_DIR) / f"{KEY_MANUAL}.py").write_text(MANUAL_SCENARIO, "utf-8")
    scenarios.invalidate(KEY_MANUAL)

    art = Path(config.ARTIFACTS_DIR) / JOB_ID
    art.mkdir(parents=True, exist_ok=True)
    (art / "99_failure.jpg").write_bytes(draw_screen())
    xml = hierarchy_xml()
    (art / "failure_hierarchy.xml").write_text(xml, "utf-8")
    (art / "failure_size.json").write_text(json.dumps({"width": W, "height": H}), "utf-8")
    nodes = uitree.parse(xml, W, H)
    payload = uitree.to_payload(nodes)
    assert nodes and payload, "дамп не разобрался в узлы"

    miss = json.dumps({"sel": [{"text": "Войти"}], "text": ["Войти"], "img": "",
                       "at": [0.5, 0.8]}, ensure_ascii=False)
    ids = {}
    for name, key, sname, shot, sig, title, step in (
            ("repair", KEY, "Демо: вход", "99_failure.jpg", "demo-a",
             "Не найден элемент «Войти» на шаге 2", 1),
            ("manual", KEY_MANUAL, "Демо: ручной сценарий", "99_failure.jpg", "demo-b",
             "Не найден элемент «Войти» (сценарий без рецепта)", -1),
            ("gone", KEY, "Демо: вход", "77_deleted.jpg", "demo-c",
             "Не найден элемент «Войти» — снимок уже удалён", 1)):
        item = dv.deviations.record(
            dv.FAIL, title, detail="демо-данные", device_name="Демо-телефон",
            job_id=JOB_ID, scenario_key=key, scenario_name=sname, shot=shot,
            miss=miss, step_index=step, signature=sig)
        ids[name] = item.id
    return {"key": KEY, "manual_key": KEY_MANUAL, "job_id": JOB_ID, "ids": ids,
            "scenario_file": str(Path(config.SCENARIOS_DIR) / f"{KEY}.py"),
            "recipe": str(Path(config.SCENARIOS_DIR) / f"{KEY}_assets" / "recipe.json"),
            "nodes": len(nodes)}


def port_busy(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args(argv)
    host = "127.0.0.1"
    if port_busy(host, args.port):
        sys.exit(f"Порт {args.port} занят. Запустите с другим: --port 8790")

    tmp = Path(tempfile.mkdtemp(prefix="farm-repair-demo-")).resolve()
    (tmp / "scenarios").mkdir()
    (tmp / "guards").mkdir()
    os.environ.update({
        "FARM_SCENARIOS_DIR": str(tmp / "scenarios"),
        "FARM_ARTIFACTS_DIR": str(tmp / "artifacts"),
        "FARM_GUARDS_DIR": str(tmp / "guards"),
        "FARM_NETWORK_FILE": str(tmp / "network.json"),
        "FARM_HOST": host, "FARM_PORT": str(args.port),
    })
    sys.path.insert(0, str(REPO))
    from farm.devices import registry
    registry.LABELS_FILE = tmp / "devices.json"   # имена телефонов — тоже во временный каталог
    info = seed(tmp)

    print(f"""
Демо починки шага запущено (без телефона).

  Адрес:            http://{host}:{args.port}
  Временный каталог: {tmp}
    (после починки загляните в {info['recipe']}
     и {info['scenario_file']}; каталог не удаляется — стирайте сами: rm -rf '{tmp}')

Что проверить:
  1. Откройте адрес, вкладка «Отклонения»: три карточки падения (новые сверху).
  2. В карточке «…на шаге 2» откройте миниатюру — скрин с маркером
     «ожидали здесь» на кнопке «Войти».
  3. Нажмите «Починить шаг»: откроется экран с рамками элементов.
  4. Кликните по «Забыли пароль?» (или выберите стрелками + Enter) —
     справа «Стало» покажет новый селектор.
  5. Нажмите «Сохранить шаг»: тост «шаг исправлен в сценарии», карточка прочитана.
  6. Проверьте файлы: в recipe.json шаг 2 теперь с текстом «Забыли пароль?»,
     а в demo_login.py вызов click_target с новой целью.
Ещё: у карточки «сценарий без рецепта» кнопки починки нет; у карточки
«снимок уже удалён» миниатюра показывает «снимок удалён».
Остановить: Ctrl+C. Ошибки adb в логе нормальны — телефонов нет.
""", flush=True)
    import uvicorn
    from farm.server import app
    uvicorn.run(app, host=host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
