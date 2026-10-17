"""Шаги записанного сценария во время прогона: где мы и «с шага N».

Оба механизма опираются на `line_map` рекордера (строка .py → индекс шага) и
не требуют ни правок сгенерированного кода, ни его разбора руками.

* `StepTracer` — трассировка ТОЛЬКО кадра `run` сценария: на смене строки, у
  которой другой шаг, зовёт колбэк. Кадры глубже (ctx.*, adb) трассировку не
  получают, так что цена — одна проверка на вызов функции в потоке задачи.
* `module_from_step` — тот же файл, но верхнеуровневые операторы `run`,
  принадлежащие шагам до N, вырезаны из AST (номера строк сохраняются, поэтому
  traceback и line_map остаются верными).
"""
from __future__ import annotations

import ast
import sys
import types
from typing import Callable


class StepTracer:
    def __init__(self, run_code: types.CodeType, line_map: dict,
                 on_step: Callable[[int], None]) -> None:
        self._code = run_code
        self._map = line_map
        self._on_step = on_step
        self.current = -1

    def _local(self, frame, event, arg):
        if event == "line":
            idx = self._map.get(frame.f_lineno)
            if idx is not None and idx != self.current:
                self.current = idx
                self._on_step(idx)
        return self._local

    def _global(self, frame, event, arg):
        if event == "call" and frame.f_code is self._code:
            return self._local
        return None

    def __enter__(self):
        sys.settrace(self._global)
        return self

    def __exit__(self, *exc):
        sys.settrace(None)
        return False


def _cut_loop(loop: ast.For, keep) -> list:
    """Повтор при запуске «с шага» / проверке одного шага.

    Повтор целиком в диапазоне — остаётся повтором. Диапазон режет его тело
    (проверяют шаг внутри повтора, запускают с середины тела) — тело идёт
    один раз, без круга: «проверить шаг 5» не должно листать десять минут.
    Проверка самого заголовка повтора — один круг всего тела.
    """
    inner = [st for st in loop.body if keep(st.lineno)]
    if keep(loop.lineno):
        if len(inner) == len(loop.body):
            return [loop]
        return inner or list(loop.body)
    return inner


def module_from_step(sc, line_map: dict, start: int, stop: int | None = None):
    """Модуль сценария без шагов до `start` (индекс с нуля) и, если задан `stop`,
    без шагов начиная с него — так прогоняют один шаг: start=i, stop=i+1.

    Бросает ValueError, если карта строк недоступна или `start` вне сценария.
    """
    if start <= 0 and stop is None:
        return sc.module
    if not line_map:
        raise ValueError("запуск с шага доступен только записанным сценариям "
                         "с актуальным рецептом — пересохраните сценарий в конструкторе")
    if start > max(line_map.values()):
        raise ValueError(f"в сценарии нет шага {start + 1}")
    with open(sc.path, "rb") as fh:
        source = fh.read()
    tree = ast.parse(source, sc.path)
    def keep(lineno: int) -> bool:
        # Строки без номера шага (watch_popups, humanize) остаются всегда.
        return lineno not in line_map or (line_map[lineno] >= start
                                          and (stop is None or line_map[lineno] < stop))

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            body = []
            for st in node.body:
                if isinstance(st, ast.For) and st.lineno in line_map:
                    body += _cut_loop(st, keep)
                elif keep(st.lineno):
                    body.append(st)
            node.body = body or [ast.Pass()]
            break
    else:
        raise ValueError("нет функции run(ctx)")
    ast.fix_missing_locations(tree)
    code = compile(tree, sc.path, "exec", dont_inherit=True)
    module = types.ModuleType(f"{sc.module.__name__}_from{start}_to{stop}")
    module.__file__ = sc.path
    exec(code, module.__dict__)
    return module
