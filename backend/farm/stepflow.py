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


def _cut(stmts: list, keep, line_map: dict) -> tuple[list, bool]:
    """Операторы тела, что остаются в диапазоне шагов, и признак «что-то вырезано».

    Блоки (повтор — for, «с шансом» — if, «пока не найдёшь» — for) режутся
    рекурсивно. Блок целиком в диапазоне — остаётся блоком. Диапазон режет
    его тело (проверяют шаг внутри, запускают с середины) — тело идёт один
    раз и без условия: «проверить шаг 5» не должно листать десять минут или
    зависеть от шанса. Проверка самого заголовка блока — один проход тела.
    """
    out, cut = [], False
    for st in stmts:
        if isinstance(st, (ast.For, ast.If)) and st.lineno in line_map:
            inner, inner_cut = _cut(st.body, keep, line_map)
            if keep(st.lineno) and not inner_cut:
                out.append(st)
                continue
            cut = True
            if keep(st.lineno) and not inner:
                checked = _check_header(st, line_map)
                if checked is not None:
                    out.append(checked)
                    continue
                inner, _ = _cut(st.body, lambda n: True, line_map)
            out += inner
        elif keep(st.lineno):
            out.append(st)
        else:
            cut = True
    return out, cut


def _ctx_call(node, name: str):
    """Вызов ctx.<name>(…) в условии/итераторе блока (в том числе под not)."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        node = node.operand
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == name):
        return node
    return None


def _check_header(st, line_map: dict):
    """Проверка одного заголовка блока с условием — условие проверяется по-
    настоящему, а не пропускается. «Если на экране» остаётся «если» (шаги
    внутри — только если цель есть/нет). «Пока не найдёшь» — один круг:
    цель уже на экране — шаги не выполняются, нет — выполняются раз и
    дальше без ошибки. Повтор и «иногда» — как раньше, один проход тела."""
    body, _ = _cut(st.body, lambda n: True, line_map)
    if isinstance(st, ast.If) and _ctx_call(st.test, "seen"):
        st.body = body or [ast.Pass()]
        st.orelse = []
        return st
    call = _ctx_call(st.iter, "until_found") if isinstance(st, ast.For) else None
    if call is not None:
        call.keywords = [kw for kw in call.keywords if kw.arg not in ("tries", "on_fail")]
        call.keywords += [ast.keyword(arg="tries", value=ast.Constant(1)),
                          ast.keyword(arg="on_fail", value=ast.Constant("skip"))]
        st.body = body or [ast.Pass()]
        return st
    return None


class _LooseBreak(ast.NodeTransformer):
    """`break`, чей повтор при вырезании развернулся в один проход, — в `pass`:
    иначе модуль не скомпилируется («break outside loop»)."""

    def visit_For(self, node):
        return node          # break внутри живого повтора — его собственный

    visit_While = visit_For

    def visit_Break(self, node):
        return ast.copy_location(ast.Pass(), node)


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
            body, _ = _cut(node.body, keep, line_map)
            node.body = [_LooseBreak().visit(st) for st in body] or [ast.Pass()]
            break
    else:
        raise ValueError("нет функции run(ctx)")
    ast.fix_missing_locations(tree)
    code = compile(tree, sc.path, "exec", dont_inherit=True)
    module = types.ModuleType(f"{sc.module.__name__}_from{start}_to{stop}")
    module.__file__ = sc.path
    exec(code, module.__dict__)
    return module
