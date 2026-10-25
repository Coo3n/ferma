"""Библиотека готовых скриптов: каждый пресет обязан порождать валидные шаги."""
import pytest

from farm.recorder import presets, steps


def _dummy(spec):
    if spec.get("choices"):
        return next(iter(spec["choices"]))   # первый вариант выбора
    if spec.get("version"):
        return "8.40"
    return "1.5" if spec.get("number") else "com.example.app"


@pytest.mark.parametrize("preset", presets.PRESETS,
                         ids=[p["key"] for p in presets.PRESETS])
def test_пресет_проходит_normalize_step(preset):
    values = {spec["name"]: _dummy(spec) for spec in preset.get("inputs", [])}
    filled = presets.fill(preset, values)
    assert filled, f"пресет {preset['key']} без шагов"
    for step in filled:
        steps.normalize_step(step)


@pytest.mark.parametrize("preset", presets.PRESETS,
                         ids=[p["key"] for p in presets.PRESETS])
def test_каждый_плейсхолдер_описан_в_inputs(preset):
    names = {spec["name"] for spec in preset.get("inputs", [])}
    for step in preset["steps"]:
        for value in step["args"].values():
            if isinstance(value, str):
                for name in presets.PLACEHOLDER_RE.findall(value):
                    assert name in names, (
                        f"пресет {preset['key']}: {{{name}}} не описан в inputs")


def test_ключи_пресетов_уникальны():
    keys = [p["key"] for p in presets.PRESETS]
    assert len(keys) == len(set(keys))


def test_подстановка_значений():
    preset = next(p for p in presets.PRESETS if p["key"] == "restart_app")
    filled = presets.fill(preset, {"package": "com.a"})
    assert [s["args"] for s in filled] == [
        {"package": "com.a"}, {"seconds": 1}, {"package": "com.a"},
    ]


def test_приложение_готово_по_умолчанию_ставит():
    preset = next(p for p in presets.PRESETS if p["key"] == "ensure_app")
    filled = presets.fill(preset, {"package": "com.a.b", "min_version": ""})
    assert steps.normalize_step(filled[0])["args"] == {"package": "com.a.b", "install": True}


@pytest.mark.parametrize("preset", presets.PRESETS,
                         ids=[p["key"] for p in presets.PRESETS])
def test_у_пресета_есть_раздел_и_слова_поиска(preset):
    assert preset["group"] in presets.GROUPS
    kw = preset["keywords"]
    assert kw and all(isinstance(k, str) and k.strip() for k in kw)
    assert len(kw) == len({k.lower() for k in kw})
    assert preset["title"].lower() not in {k.lower() for k in kw}


def test_группы_фиксированы():
    assert list(presets.GROUPS) == ["apps", "gestures", "feed", "input",
                                    "network", "wait", "system"]


def test_эндпоинт_отдаёт_group_и_keywords():
    from farm.api import recorder
    rows = recorder.preset_list()
    assert all("group" in r and "keywords" in r for r in rows)
