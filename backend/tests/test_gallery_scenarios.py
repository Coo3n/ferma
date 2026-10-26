"""Каждый готовый сюжет описан, совместим с формой запуска и понятен словами."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from farm import config, scenarios, steps_text
from farm.recorder import codegen, steps as schema, validate

GALLERY = Path(config.ROOT) / "scenarios" / "gallery"
CODE = ["tiktok_feed", "spotify_listener", "telegram_channels"]
RECIPES = ["shorts_autoscroll", "vk_feed", "youtube_shorts", "spotify_one", "telegram_one"]
RAW_ID = re.compile(r"resourceId|:id/|android\.widget|\.\*|\(\?i\)")


def load(key):
    spec = importlib.util.spec_from_file_location(f"gallery_test_{key}", GALLERY / f"{key}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def recipe(key):
    return json.loads((GALLERY / f"{key}.recipe.json").read_text("utf-8"))


def test_all_expected_scenarios_exist():
    assert sorted(p.stem for p in GALLERY.glob("*.py")) == sorted(CODE)
    assert sorted(p.name[:-len(".recipe.json")] for p in GALLERY.glob("*.recipe.json")) == sorted(RECIPES)


@pytest.mark.parametrize("key", CODE)
def test_code_scenario_is_described_and_unverified(key):
    mod = load(key)
    assert callable(mod.run)
    assert mod.NAME and mod.DESCRIPTION
    assert mod.GALLERY["platform"] and mod.GALLERY["package"]
    assert mod.GALLERY["verified"] is False


@pytest.mark.parametrize("key", CODE)
def test_code_scenario_has_plain_steps(key):
    steps = load(key).STEPS
    assert 6 <= len(steps) <= 12
    assert all(isinstance(s, str) and s.strip() and not RAW_ID.search(s) for s in steps)


def test_list_scenarios_are_marked_by_list():
    assert load("spotify_listener").NAME.endswith("(по списку)")
    assert load("telegram_channels").NAME.endswith("(по списку)")


@pytest.mark.parametrize("key", CODE)
def test_params_are_valid_form_fields(key):
    mod = load(key)
    for name, spec in mod.PARAMS.items():
        assert spec.get("label"), name
        assert spec.get("type") in (None, "number", "bool", "textarea"), name
        if spec.get("options"):
            assert spec["default"] in spec["options"], name


@pytest.mark.parametrize("key", CODE)
def test_default_params_resolve(key):
    mod = load(key)
    sc = scenarios.Scenario(key, mod.NAME, mod.DESCRIPTION, mod.PARAMS, "", 0.0)
    resolved = scenarios.resolve_params(sc, {})
    assert set(mod.PARAMS) <= set(resolved)


def test_tiktok_accepts_default_form():
    from farm import feed
    mod = load("tiktok_feed")
    sc = scenarios.Scenario("tiktok_feed", mod.NAME, mod.DESCRIPTION, mod.PARAMS, "", 0.0)
    params = scenarios.resolve_params(sc, {"words": "кошки\nсобаки"})
    assert feed.from_params(params, label="x", allowed=mod.ALLOWED).views >= 1


@pytest.mark.parametrize("key", RECIPES)
def test_recipe_is_described_and_unverified(key):
    data = recipe(key)
    assert data["key"] == key
    assert data["gallery"]["platform"] and data["gallery"]["package"]
    assert data["gallery"]["verified"] is False
    meta = schema.normalize_meta(data["meta"])
    assert meta["name"] and meta["description"]
    assert meta["watch_popups"] is True and meta["human"] is True


@pytest.mark.parametrize("key", RECIPES)
def test_recipe_passes_schema_codegen_and_validate(key):
    data = recipe(key)
    meta = schema.normalize_meta(data["meta"])
    params = schema.normalize_params(data["params"])
    steps = schema.normalize_steps(data["steps"])
    schema.check_params(params, steps)
    compile(codegen.render(meta, params, steps), key, "exec")
    result = validate.validate({"meta": data["meta"], "params": data["params"], "steps": data["steps"]})
    assert result["errors"] == []


@pytest.mark.parametrize("key", RECIPES)
def test_recipe_steps_read_in_plain_words(key):
    steps = schema.normalize_steps(recipe(key)["steps"])
    lines = steps_text.describe(steps)
    assert len(lines) == len(steps)
    for line in lines:
        assert line["text"].strip() and not RAW_ID.search(line["text"]), line


def test_recipe_selectors_keep_known_ids():
    vk = json.dumps(recipe("vk_feed"), ensure_ascii=False)
    assert "com.vkontakte.android:id/iv_likes" in vk and "0.064" in vk
    sp = json.dumps(recipe("spotify_one"), ensure_ascii=False)
    assert "com.spotify.music:id/search_tab" in sp and "find_search_field" in sp
