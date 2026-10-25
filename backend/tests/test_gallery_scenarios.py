"""Каждый готовый сюжет импортируется, описан и совместим с формой запуска."""
import importlib.util
from pathlib import Path

import pytest

from farm import config, scenarios

GALLERY = Path(config.ROOT) / "scenarios" / "gallery"
KEYS = ["tiktok_feed", "shorts_autoscroll", "spotify_listener",
        "vk_feed", "telegram_channels", "youtube_shorts"]


def load(key):
    spec = importlib.util.spec_from_file_location(f"gallery_test_{key}", GALLERY / f"{key}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_expected_scenarios_exist():
    assert sorted(p.stem for p in GALLERY.glob("*.py")) == sorted(KEYS)


@pytest.mark.parametrize("key", KEYS)
def test_scenario_is_described_and_unverified(key):
    mod = load(key)
    assert callable(mod.run)
    assert mod.NAME and mod.DESCRIPTION
    assert mod.GALLERY["platform"] and mod.GALLERY["package"]
    assert mod.GALLERY["verified"] is False


@pytest.mark.parametrize("key", KEYS)
def test_params_are_valid_form_fields(key):
    mod = load(key)
    for name, spec in mod.PARAMS.items():
        assert spec.get("label"), name
        assert spec.get("type") in (None, "number", "bool", "textarea"), name
        if spec.get("options"):
            assert spec["default"] in spec["options"], name


@pytest.mark.parametrize("key", KEYS)
def test_default_params_resolve(key):
    mod = load(key)
    sc = scenarios.Scenario(key, mod.NAME, mod.DESCRIPTION, mod.PARAMS, "", 0.0)
    resolved = scenarios.resolve_params(sc, {})
    assert set(mod.PARAMS) <= set(resolved)


@pytest.mark.parametrize("key", ["tiktok_feed", "vk_feed", "youtube_shorts"])
def test_feed_scenarios_accept_default_form(key):
    from farm import feed
    mod = load(key)
    sc = scenarios.Scenario(key, mod.NAME, mod.DESCRIPTION, mod.PARAMS, "", 0.0)
    params = scenarios.resolve_params(sc, {"words": "кошки\nсобаки"})
    assert feed.from_params(params, label="x", allowed=mod.ALLOWED).views >= 1
