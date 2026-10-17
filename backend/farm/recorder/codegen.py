"""Сборка исходника сценария из проверенных шагов.

На входе словари, на выходе строка: ни adb, ни FastAPI, ни файловой системы.
Благодаря этому весь генератор покрывается тестами без телефона.
"""
from __future__ import annotations

from datetime import date

INDENT = "    "


def literal(value) -> str:
    """Строковый литерал Python.

    Единственный источник литералов: им же пользуется farm/ui/selectors.
    Перевод строки или другой управляющий символ, записанный сырым, даёт .py,
    который не компилируется, — сценарий мёртв для всех устройств.
    """
    out = []
    for ch in str(value):
        if ch == "\\" or ch == '"':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\x{ord(ch):02x}")  # прочие управляющие: сырыми не пишем
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _comment(text) -> str:
    """Текст для `# ...`: любой перевод строки или управляющий символ начал бы
    в .py новую строку кода, поэтому они заменяются пробелом."""
    return "".join(" " if (ord(c) < 32 or ord(c) == 127 or c in "\x85\u2028\u2029") else c
                   for c in str(text))


def _num(value) -> str:
    """Число без хвостовых нулей: 1.0 → 1, 0.4200 → 0.42."""
    return f"{round(float(value), 3):g}"


def _default(value) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return _num(value)
    return literal(value)


def _value(step: dict, fallback: str) -> str:
    """Вынесенный параметр вместо литерала, если он задан."""
    name = step.get("param")
    return f"ctx.params[{literal(name)}]" if name else fallback


# Переменная развилки. Одна на все ветвления в файле: два развилочных шага
# подряд переиспользуют её, и это честнее, чем ветка1/ветка2 — к моменту
# второй развилки результат первой уже отработан.
BRANCH_VAR = "ветка"


def _branch(step: dict) -> list:
    """Развилка: определить экран и выполнить блок той ветки, что совпала.

    Единственный шаг, который занимает больше одной строки: ветвление и есть
    несколько строк, а прятать его в один вызов значило бы прятать сюжет.
    Блоки зовутся через ctx.run — тот же механизм, что у отводов, со своей
    защитой от рекурсии и потолком вложенности.
    """
    args = step["args"]
    arms = step["arms"]
    хвост = []
    таймаут = args.get("timeout")
    if таймаут is not None:
        хвост.append(f"timeout={_num(таймаут)}")
    if not step.get("report", True):
        хвост.append("report=False")

    out = [f"{BRANCH_VAR} = ctx.which_screen({{"]
    for arm in arms:
        признаки = ", ".join(f"dict({a})" for a in arm["any"])
        out.append(f'{INDENT}{literal(arm["name"])}: [{признаки}],')
    out.append("}" + (", " + ", ".join(хвост) if хвост else "") + ")")

    for arm in arms:
        if not arm["run"]:
            continue        # ветка знакома, делать на ней нечего
        out.append(f'if {BRANCH_VAR} == {literal(arm["name"])}:')
        out.append(f'{INDENT}ctx.run({literal(arm["run"])})')
    return out


def _loop(step: dict) -> str:
    """Заголовок повтора; тело — следующие span шагов с отступом (render_mapped)."""
    args = step["args"]
    parts = [f'times={int(args["times"])}' if args.get("times") is not None
             else f'minutes={_num(args["minutes"])}']
    if args.get("pause_min") is not None:
        parts.append(f'pause=({_num(args["pause_min"])}, {_num(args["pause_max"])})')
    if args.get("watch"):
        parts.append("watch=True")
    return f"for _ in ctx.loop({', '.join(parts)}):"


def _chance(step: dict) -> str:
    return f'if ctx.chance({_num(step["args"]["percent"])}):'


def _until(step: dict) -> str:
    """Заголовок «пока не найдёшь»: тело крутится, пока цели нет на экране."""
    args = step["args"]
    цель = ", ".join(f"dict({a})" for a in step["any"])
    хвост = [f'tries={int(args.get("tries", 20))}']
    if args.get("on_fail", "skip") != "skip":
        хвост.append(f'on_fail={literal(args["on_fail"])}')
    return f'for _ in ctx.until_found([{цель}], {", ".join(хвост)}):'


BLOCK_HEADERS = {"loop": _loop, "chance": _chance, "until": _until}


def _call(step: dict):
    """Строка вызова — или список строк, если шаг в одну не укладывается."""
    kind, args = step["kind"], step["args"]

    if kind == "branch":
        return _branch(step)
    if kind in BLOCK_HEADERS:
        return BLOCK_HEADERS[kind](step)

    if kind == "click":
        selector = step["selector"]
        chain = [selector["args"], *(selector.get("fallbacks") or [])]
        texts = step.get("texts") or []
        crop = step.get("crop")
        point = step.get("point")
        if texts or crop or point:
            parts = ["sel=[" + ", ".join(f"dict({a})" for a in chain) + "]"]
            if texts:
                parts.append("text=[" + ", ".join(literal(t) for t in texts) + "]")
            if crop:
                parts.append(f"img={literal(crop)}")
            if point:
                parts.append(f"at=({_num(point[0])}, {_num(point[1])})")
            return "ctx.click_target(" + ", ".join(parts) + ")"
        if len(chain) > 1:
            return "ctx.click_any(" + ", ".join(f"dict({a})" for a in chain) + ")"
        return f"ctx.click({chain[0]})"
    if kind == "expect":
        chain = ", ".join(f"dict({a})" for a in step["any"])
        return f'ctx.expect_screen({literal(args["name"])}, any=[{chain}])'
    if kind == "tap":
        return f'ctx.tap({_num(args["x"])}, {_num(args["y"])})'
    if kind == "long_tap":
        return (f'ctx.long_tap({_num(args["x"])}, {_num(args["y"])}, '
                f'{_num(args.get("duration", 0.8))})')
    if kind == "swipe":
        return (f'ctx.swipe({_num(args["x1"])}, {_num(args["y1"])}, '
                f'{_num(args["x2"])}, {_num(args["y2"])}, '
                f'{_num(args.get("duration", 0.25))})')
    if kind == "type":
        tail = ", clear=True" if args.get("clear") else ""
        if args.get("account"):
            return (f'ctx.type(ctx.account({literal(args["account"])})'
                    f'[{literal(args["field"])}]{tail})')
        return f'ctx.type({_value(step, literal(args["value"]))}{tail})'
    if kind == "key":
        return f'ctx.key({literal(args["name"])})'
    if kind == "unlock":
        return "ctx.unlock()"
    if kind == "launch_app":
        return f'ctx.launch_app({_value(step, literal(args["package"]))})'
    if kind == "stop_app":
        return f'ctx.stop_app({_value(step, literal(args["package"]))})'
    if kind == "open_url":
        return f'ctx.open_url({_value(step, literal(args["url"]))})'
    if kind == "shell":
        return f'ctx.shell({_value(step, literal(args["cmd"]))})'
    if kind == "sleep":
        return f'ctx.sleep({_value(step, _num(args["seconds"]))})'
    if kind == "screenshot":
        name = args.get("name", "")
        inner = _value(step, literal(name)) if (name or step.get("param")) else ""
        return f"ctx.screenshot({inner})"
    raise ValueError(f"неизвестный шаг: {kind}")  # недостижимо после normalize_step


def _flexible(call: str, step: dict, index: int) -> str:
    """`ctx.attempt(lambda: <вызов>, ...)`: повтор и/или пропуск при неудаче."""
    extra = []
    if step.get("retries"):
        extra.append(f"retries={int(step['retries'])}")
    if step.get("optional"):
        extra.append("optional=True")
    extra.append(f"what={literal(f'шаг {index + 1}')}")
    return f"ctx.attempt(lambda: {call}, " + ", ".join(extra) + ")"


def _header(meta: dict, params: dict, today: date) -> list:
    out = [f'"""Записано конструктором фермы {today.strftime("%d.%m.%Y")}."""',
           "RECORDED = True",
           f'NAME = {literal(meta["name"])}']
    if meta.get("description"):
        out.append(f'DESCRIPTION = {literal(meta["description"])}')
    if params:
        out.append("PARAMS = {")
        for name, spec in params.items():
            out.append(f'{INDENT}{literal(name)}: '
                       f'{{"label": {literal(spec["label"])}, '
                       f'"default": {_default(spec["default"])}}},')
        out.append("}")
    return out


def render(meta: dict, params: dict, steps: list, today: date = None) -> str:
    """Готовый текст файла сценария."""
    return render_mapped(meta, params, steps, today)[0]


def render_mapped(meta: dict, params: dict, steps: list,
                  today: date = None) -> tuple[str, dict[int, int]]:
    """Текст файла и карта {номер строки (с 1) → индекс шага в `steps`}.

    По ней трейсбэк упавшего сценария превращается в шаг конструктора.
    Строки многострочного шага (развилка с телами веток) целиком отображаются
    на него. Служебные ctx.watch_popups()/humanize() в карте отсутствуют.
    """
    out = _header(meta, params, today or date.today())
    out += ["", "", "def run(ctx):"]

    body = []
    owners = []  # индекс шага для каждой строки body, None у служебных
    if meta.get("watch_popups", True):
        body.append("ctx.watch_popups()")
        owners.append(None)
    if meta.get("human"):
        body.append("ctx.humanize()")
        owners.append(None)
    ends = []   # индексы последних шагов тел открытых блоков, внешний первым
    for index, step in enumerate(steps):
        while ends and index > ends[-1]:
            ends.pop()
        строки = _call(step)
        if isinstance(строки, str):
            строки = [строки]
        else:
            строки = list(строки)
        if step.get("optional") or step.get("retries"):
            # Устойчивость шага — обёртка над единственной строкой вызова.
            # Допустима лишь у одностроковых шагов (см. steps.FLEXIBLE).
            if len(строки) == 1:
                строки = [_flexible(строки[0], step, index)]
        note = step.get("note")
        if note:
            # Комментарий вешается на первую строку: у многострочного шага она
            # и есть сам шаг, остальные — его тело.
            строки[0] += f"  # {_comment(note)}"
        if ends:
            строки = [INDENT * len(ends) + line for line in строки]
        if step["kind"] in BLOCK_HEADERS:
            ends.append(index + step["args"]["span"])
        body += строки
        owners += [index] * len(строки)
    if not body:
        body.append("pass")  # пустой def run(ctx) — синтаксическая ошибка
        owners.append(None)

    # номера считаются по фактическому выводу: шапка бывает разной длины
    first = len(out) + 1
    line_map = {first + i: idx for i, idx in enumerate(owners) if idx is not None}
    out += [INDENT + line for line in body]
    return "\n".join(out) + "\n", line_map
