"""Безопасность записи сценария: атомарность, хэш кода, чужие файлы, инъекции."""
import base64
import hashlib
import json
import os

import pytest
from fastapi import HTTPException

from farm import config, scenarios
from farm.recorder import save, steps

META = {"name": "Тест", "description": "", "watch_popups": False}
ШАГ = steps.normalize_step({"kind": "unlock", "args": {}})
STEPS = [ШАГ]
PNG = base64.b64encode(b"png").decode()


def _click(args, **kw):
    return steps.normalize_step({"kind": "click",
                                 "selector": {"call": "click", "args": args}, **kw})


@pytest.fixture
def scen_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    return tmp_path


def _state(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _first(scen_dir):
    save.save("k", META, {}, [_click('text="Ок"', crop="01_a.png")],
              assets={"01_a.png": PNG, "02_b.png": PNG}, screen_width=1080)
    return _state(scen_dir)


# ---- 1. атомарность ----

@pytest.mark.parametrize("assets", [{"x.png": "не base64!"},
                                    {"Bad Name.png": PNG},
                                    {f"{i}.png": PNG for i in range(61)}])
def test_отказ_проверки_ассетов_не_трогает_диск(scen_dir, assets):
    before = _first(scen_dir)
    with pytest.raises(save.SaveError):
        save.save("k", META, {}, STEPS, overwrite=True, assets=assets)
    assert _state(scen_dir) == before


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_сбой_на_любой_замене_откатывает_всё(scen_dir, monkeypatch, n):
    before = _first(scen_dir)
    real, calls = os.replace, []

    def flaky(a, b):
        calls.append(b)
        if len(calls) == n:
            raise OSError("диск")
        return real(a, b)
    monkeypatch.setattr(os, "replace", flaky)
    with pytest.raises(OSError):
        save.save("k", META, {}, STEPS, overwrite=True,
                  assets={"03_c.png": PNG}, screen_width=720)
    monkeypatch.setattr(os, "replace", real)
    assert _state(scen_dir) == before


def test_сбой_записи_временного_файла_ничего_не_меняет(scen_dir, monkeypatch):
    before = _first(scen_dir)
    real = type(scen_dir).write_bytes
    count = []

    def flaky(self, data):
        count.append(1)
        if len(count) == 3:
            raise OSError("нет места")
        return real(self, data)
    monkeypatch.setattr(type(scen_dir), "write_bytes", flaky)
    with pytest.raises(OSError):
        save.save("k", META, {}, STEPS, overwrite=True, assets={"03_c.png": PNG})
    monkeypatch.setattr(type(scen_dir), "write_bytes", real)
    assert _state(scen_dir) == before


def test_лишние_кропы_и_meta_убираются_после_успеха(scen_dir):
    _first(scen_dir)
    save.save("k", META, {}, STEPS, overwrite=True, assets={"03_c.png": PNG})
    names = sorted(p.name for p in (scen_dir / "k_assets").iterdir())
    assert names == ["03_c.png", "recipe.json"]  # без старых png и без meta.json


def test_временные_файлы_не_остаются(scen_dir):
    _first(scen_dir)
    assert not [p for p in scen_dir.rglob("*") if p.name.endswith(".tmp")]


# ---- 2. code_sha256 ----

def test_хэш_кода_совпадает_с_байтами_файла(scen_dir):
    path = save.save("k", META, {}, [_click('text="Купить\\n1"')])
    assert save.load_code_sha256("k") == hashlib.sha256(path.read_bytes()).hexdigest()


def test_хэш_пуст_у_старого_рецепта_и_без_рецепта(scen_dir):
    assert save.load_code_sha256("k") == ""
    save.save("k", META, {}, STEPS)
    r = save.recipe_path("k")
    data = json.loads(r.read_text("utf-8"))
    del data["code_sha256"]
    r.write_text(json.dumps(data), "utf-8")
    assert save.load_code_sha256("k") == ""
    r.write_text("{битый", "utf-8")
    assert save.load_code_sha256("k") == ""


# ---- 3. чужой файл ----

def test_перезапись_рукописного_файла_409(scen_dir):
    (scen_dir / "hand.py").write_text("# мой файл\n", "utf-8")
    with pytest.raises(save.Conflict):
        save.save("hand", META, {}, STEPS, overwrite=True)
    assert (scen_dir / "hand.py").read_text("utf-8") == "# мой файл\n"


def test_api_рукописный_409_и_рецепт_сирота_404(scen_dir):
    from farm.api import recorder as api
    (scen_dir / "hand.py").write_text("# мой файл\n", "utf-8")
    body = {"key": "hand", "meta": META, "params": {},
            "steps": [{"kind": "unlock", "args": {}}], "overwrite": True}
    with pytest.raises(HTTPException) as e:
        api.save_scenario(body)
    assert e.value.status_code == 409 and "вручную" in e.value.detail
    save.save("orph", META, {}, STEPS)
    assert api.recipe("orph")["key"] == "orph"
    (scen_dir / "orph.py").write_text("# руками\n", "utf-8")
    with pytest.raises(HTTPException) as e:
        api.recipe("orph")
    assert e.value.status_code == 404
    (scen_dir / "orph.py").unlink()
    with pytest.raises(HTTPException) as e:
        api.recipe("orph")
    assert e.value.status_code == 404


def test_правка_своего_сценария_проходит(scen_dir):
    save.save("k", META, {}, STEPS)
    save.save("k", META, {}, STEPS, overwrite=True)


# ---- 4. переводы строк ----

def test_текст_с_переводами_строк_компилируется(scen_dir):
    text = "Купить\n1 299\r\n\tза\x01шт"
    from farm.ui import selectors
    args = f"text={selectors._literal(text)}"
    path = save.save("k", META, {}, [_click(args)])
    ns = {}
    compile(path.read_bytes(), str(path), "exec")
    assert eval(f"dict({args})") == {"text": text}


def test_страховка_компиляции(scen_dir, monkeypatch):
    from farm.recorder import codegen
    monkeypatch.setattr(codegen, "render_mapped",
                        lambda *a: ('x = "\n', {}))
    with pytest.raises(save.SaveError):
        save.save("k", META, {}, STEPS)
    assert not list(scen_dir.iterdir())


# ---- 5. грамматика args ----

@pytest.mark.parametrize("args", [
    'text="Войти"',
    'text="Он сказал \\"да\\" и \\\\"',
    'resourceId="a:id/b", className="android.view.View", instance=3',
    'clickable=True',
    'textContains="Корзина"',
    'description="Ёж\\n2"',
])
def test_допустимые_аргументы(args):
    assert _click(args, )["selector"]["args"] == args
    assert steps.normalize_step({"kind": "click", "selector": {
        "call": "click", "args": 'text="a"', "fallbacks": [args]}})


@pytest.mark.parametrize("args", [
    'text="a")\nimport os\nx=(1',
    'text="a"\n',
    'text=__import__("os").system("x")',
    'text=open("f")',
    'text="a".upper()',
    'text=os.name',
    '*x',
    '**x',
    'text=f"{1}"',
    'text="a" # хвост',
    '#',
    'text="a"), ctx.stop(',
    '"a"',
    'text=b"a"',
    'x=1.5',
    'x=None',
    'x=-1',
    'x=[1]',
    '',
])
def test_инъекции_отвергаются(args):
    with pytest.raises(steps.StepError):
        _click(args)
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "click", "selector": {
            "call": "click", "args": 'text="a"', "fallbacks": [args or " x"]}})


def test_все_рецепты_репозитория_проходят():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent / "scenarios"
    # scenarios/ в .gitignore: в чистом клоне и в worktree рецептов нет, а
    # оператор может удалить последний. Пустая папка — нечего проверять, а не
    # поломка; падать надо на рецепте, который не проходит.
    recipes = sorted(root.glob("*_assets/recipe.json"))
    if not recipes:
        pytest.skip("в scenarios/ нет записанных рецептов")
    for f in recipes:
        for st in json.loads(f.read_text("utf-8"))["steps"]:
            steps.normalize_step(st)
