"""Инъекции через признаки экрана и прочие строки, что кодоген вставляет в .py."""
import pytest

from farm import config
from farm.recorder import codegen, save, steps

META = {"name": "Тест", "description": "", "watch_popups": False}
EVIL = 'text="a"),\nimport os; open("/tmp/pwned","w")\n#'


@pytest.fixture
def scen_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    return tmp_path


def _expect(any_):
    return {"kind": "expect", "args": {"name": "x"}, "any": any_}


def _branch(any_, **arm):
    return {"kind": "branch", "args": {"name": "b"},
            "arms": [{"name": "a", "any": any_, **arm}]}


@pytest.mark.parametrize("raw", [
    _expect([EVIL]),
    _expect(['text="ok"', EVIL]),
    _expect(['text="a", x=__import__("os")']),
    _branch([EVIL]),
    _branch(['text="a"'], run="ok\nimport os"),
])
def test_инъекция_в_признаки_отвергается(raw):
    with pytest.raises(steps.StepError):
        steps.normalize_step(raw)


def test_легальные_признаки_проходят():
    s = steps.normalize_step(_expect(['text="Ок", clickable=True', 'resourceId="a:id/b"']))
    assert s["any"] == ['text="Ок", clickable=True', 'resourceId="a:id/b"']
    assert steps.normalize_step(_branch(['text="a"']))["arms"][0]["any"] == ['text="a"']


def test_заметка_с_переводом_строки_остаётся_комментарием():
    s = steps.normalize_step({"kind": "unlock", "note": "a\nimport os\x0b\x1c x"})
    code = codegen.render(META, {}, [s])
    compile(code, "x", "exec")
    assert "import os" not in [l.strip() for l in code.splitlines()]


def test_сырой_шаг_в_кодогене_не_ломает_структуру():
    # кодоген могут позвать и с шагом, минующим normalize: заметка режется сама
    step = {"kind": "unlock", "args": {}, "note": "a\nimport os"}
    assert "\nimport os" not in codegen.render(META, {}, [step])


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_нечисловые_аргументы_отвергаются(bad):
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "tap", "args": {"x": bad, "y": 1}})
    with pytest.raises(steps.StepError):
        steps.normalize_params({"p": {"default": bad}})


def test_имена_и_значения_с_кавычками_и_переводами_идут_литералом(scen_dir):
    meta = steps.normalize_meta({"name": 'a"\nimport os', "description": '"""\nimport os'})
    params = steps.normalize_params({"p": {"label": 'x"\nimport os', "default": 'd"\nimport os'}})
    st = [steps.normalize_step({"kind": "type", "args": {"value": 'v"\nx'}, "param": "p"}),
          steps.normalize_step(_branch(['text="a"'], run="ok")
                               | {"arms": [{"name": 'n"\nimport os', "any": ['text="a"'], "run": "ok"}]})]
    save.save("k", meta, params, st)
    code = (scen_dir / "k.py").read_text("utf-8")
    ns = {}
    exec(compile(code, "k", "exec"), ns)
    assert ns["NAME"] == 'a" import os'   # _text схлопывает переводы строк
    assert ns["PARAMS"]["p"]["default"] == 'd"\nimport os'


def test_инъекция_через_save_не_пишет_файлов(scen_dir):
    with pytest.raises(steps.StepError):
        steps.normalize_steps([_expect([EVIL])])
    assert list(scen_dir.iterdir()) == []


# ---- откат и сообщения об ошибках ----
import base64
import os
import threading
from pathlib import Path

from fastapi import HTTPException

from farm import scenarios
from farm.api import detours as api_detours
from farm.api import recorder as api_recorder
from farm.api import scenarios as api_scenarios

PNG = base64.b64encode(b"png").decode()
STEP = steps.normalize_step({"kind": "unlock", "args": {}})
RAW = {"key": "k", "meta": META, "steps": [{"kind": "unlock", "args": {}}]}


def _state(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _first():
    save.save("k", META, {}, [STEP], assets={"01_a.png": PNG}, screen_width=1080)


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root читает всё")
def test_нечитаемый_файл_не_считается_отсутствующим(scen_dir, monkeypatch):
    _first()
    png = scen_dir / "k_assets" / "01_a.png"
    png.chmod(0)
    try:
        before = {p: p.read_bytes() for p in scen_dir.rglob("*") if p.is_file() and p != png}
        with pytest.raises(save.SaveError) as e:
            save.save("k", META, {}, [STEP], overwrite=True, assets={"02_b.png": PNG})
        assert getattr(e.value, "rolled_back", None) is True
        assert png.exists()   # не удалён откатом
        assert {p: p.read_bytes() for p in before} == before
    finally:
        png.chmod(0o644)


def _count(monkeypatch, owner, name, fail_at, only=None):
    real, calls = getattr(owner, name), []

    def wrapper(*a, **k):
        target = a[1] if owner is os else a[0]
        if only and not only(target):
            return real(*a, **k)
        calls.append(target)
        if len(calls) == fail_at:
            raise OSError("boom")
        return real(*a, **k)
    monkeypatch.setattr(owner, name, wrapper)
    return calls


def test_сбой_уборки_tmp_не_пропускает_откат(scen_dir, monkeypatch):
    _first()
    before = _state(scen_dir)
    _count(monkeypatch, os, "replace", 3)      # сбой на .py -> нужен откат
    real = Path.unlink

    def bad_unlink(self, *a, **k):
        if self.name.endswith(".tmp"):
            raise OSError("unlink")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", bad_unlink)
    with pytest.raises(save.SaveError):
        save.save("k", META, {}, [STEP, STEP], overwrite=True,
                  assets={"01_a.png": base64.b64encode(b"new").decode()}, screen_width=720)
    monkeypatch.setattr(Path, "unlink", real)
    got = {k: v for k, v in _state(scen_dir).items() if not k.endswith(".tmp")}
    assert got == before


def test_откат_трогает_только_заменённое(scen_dir, monkeypatch):
    _first()
    (scen_dir / "k_assets" / "01_a.png").write_bytes(b"png")
    writes = []
    real = Path.write_bytes

    def spy(self, data):
        writes.append(self.name)
        return real(self, data)
    _count(monkeypatch, os, "replace", 1)      # падает на самой первой замене
    monkeypatch.setattr(Path, "write_bytes", spy)
    with pytest.raises(save.SaveError):
        save.save("k", META, {}, [STEP], overwrite=True, assets={"01_a.png": PNG})
    # ничего не заменено -> откат не пишет ни одного файла сверх плана
    # (png, .py, recipe.json)
    assert len(writes) == 3


def test_сбой_записи_в_откате_не_оставляет_tmp(scen_dir, monkeypatch):
    _first()
    _count(monkeypatch, os, "replace", 3)
    real = Path.write_bytes
    state = {"n": 0}

    def flaky(self, data):
        state["n"] += 1
        if state["n"] > 4:                       # план записан, дальше пишет откат
            real(self, b"half")
            raise OSError("disk")
        return real(self, data)
    monkeypatch.setattr(Path, "write_bytes", flaky)
    with pytest.raises(save.SaveError) as e:
        save.save("k", META, {}, [STEP, STEP], overwrite=True,
                  assets={"01_a.png": base64.b64encode(b"new").decode()}, screen_width=720)
    assert e.value.rolled_back is False
    assert not [p for p in scen_dir.rglob("*.tmp")]


def test_неудавшееся_первое_сохранение_не_оставляет_папку(scen_dir, monkeypatch):
    _count(monkeypatch, os, "replace", 1)
    with pytest.raises(save.SaveError):
        save.save("k", META, {}, [STEP], assets={"01_a.png": PNG})
    assert list(scen_dir.iterdir()) == []


def test_fsync_для_py_и_рецепта(scen_dir, monkeypatch):
    real, n = os.fsync, []
    monkeypatch.setattr(os, "fsync", lambda fd: (n.append(fd), real(fd))[1])
    save.save("k", META, {}, [STEP], assets={"01_a.png": PNG})
    assert len(n) == 2


def test_is_recorded_публичен(scen_dir):
    save.save("k", META, {}, [STEP])
    assert scenarios.is_recorded(scen_dir / "k.py") is True


# ---- удаление против сохранения ----

def test_удаление_держит_замок_и_сохранение_не_воскрешает(scen_dir):
    save.save("k", META, {}, [STEP], screen_width=1080)
    entered, release = threading.Event(), threading.Event()
    real_inv = scenarios.invalidate

    def slow_invalidate(key):
        entered.set()
        release.wait(5)
        real_inv(key)
    scenarios.invalidate = slow_invalidate
    try:
        d = threading.Thread(target=save.delete, args=("k",))
        d.start()
        assert entered.wait(5)                      # удаление внутри замка
        done = threading.Event()

        def saver():
            try:
                save.save("k", META, {}, [STEP], overwrite=True)
            except save.SaveError:
                pass
            done.set()
        s = threading.Thread(target=saver)
        s.start()
        assert not done.wait(0.3)                   # save ждёт замок
        release.set()
        d.join(5)
        s.join(5)
    finally:
        scenarios.invalidate = real_inv
    # save после delete: перезапись отсутствующего — обычное создание, но
    # никогда не «.py без рецепта»
    py, recipe = scen_dir / "k.py", scen_dir / "k_assets" / "recipe.json"
    assert py.exists() == recipe.exists()


def test_эндпоинт_удаления_зовёт_save_delete(scen_dir):
    api_recorder.save_scenario(RAW)
    assert api_scenarios.delete_scenario("k") == {"ok": True}
    assert _state(scen_dir) == {}


# ---- отображение ошибок ----

@pytest.mark.parametrize("bad", ["abc", float("inf"), {}, -5, [1]])
def test_кривая_ширина_экрана_400_и_диск_чист(scen_dir, bad):
    with pytest.raises(save.SaveError):
        save.save("k", META, {}, [STEP], assets={"01_a.png": PNG}, screen_width=bad)
    assert list(scen_dir.iterdir()) == []
    with pytest.raises(HTTPException) as e:
        api_recorder.save_scenario({**RAW, "screen_width": bad})
    assert e.value.status_code == 400


@pytest.mark.parametrize("call", ["recorder", "detours"])
def test_сбой_публикации_даёт_500_с_откатом(scen_dir, monkeypatch, call, tmp_path):
    _count(monkeypatch, os, "replace", 1, only=lambda p: str(p).endswith(".py"))
    with pytest.raises(HTTPException) as e:
        if call == "recorder":
            api_recorder.save_scenario(RAW)
        else:
            monkeypatch.setattr(api_detours.config, "GUARDS_DIR", tmp_path / "g", raising=False)
            api_detours.create_detour({**RAW, "when": {"text": "x"}})
    assert e.value.status_code == 500
    assert "возвращены" in e.value.detail


def test_500_без_отката_говорит_правду(scen_dir):
    err = save.SaveIOError("x", rolled_back=False)
    assert api_recorder._io_detail(err) != api_recorder._io_detail(
        save.SaveIOError("x", rolled_back=True))
