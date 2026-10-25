"""Шаг «потолок за сутки»: схема, подпись, код."""
import pytest

from farm.recorder import codegen, steps


def _step(**args):
    return steps.normalize_step({"kind": "budget", "args": args})


def test_normalizes_and_generates_code():
    st = _step(name="подписки", limit=50)
    assert st["args"] == {"name": "подписки", "limit": 50}
    assert codegen._call(st) == 'ctx.budget("подписки", 50)'
    assert steps.label_of(st) == "Потолок за сутки: подписки — не больше 50 за сутки"


def test_platform_is_optional_and_checked():
    assert codegen._call(_step(name="лайки", limit=9, platform="inst")) \
        == 'ctx.budget("лайки", 9, platform="inst")'
    assert "platform" not in _step(name="лайки", limit=9, platform="")["args"]
    with pytest.raises(steps.StepError):
        _step(name="лайки", limit=9, platform="вконтакте")


@pytest.mark.parametrize("limit", [0, -1, 1.5, 10001])
def test_bad_limit_is_rejected(limit):
    with pytest.raises(steps.StepError):
        _step(name="подписки", limit=limit)


def test_name_is_required_and_bounded():
    with pytest.raises(steps.StepError):
        _step(name="   ", limit=5)
    with pytest.raises(steps.StepError):
        _step(name="я" * (steps.BUDGET_NAME_MAX + 1), limit=5)


def test_type_step_wraps_variants_in_phrase_at_runtime():
    плоский = steps.normalize_step({"kind": "type", "args": {"value": "привет"}})
    assert codegen._call(плоский) == 'ctx.type("привет")'
    варианты = steps.normalize_step({"kind": "type", "args": {"value": "{привет|хай}"}})
    assert codegen._call(варианты) == 'ctx.type(ctx.phrase("{привет|хай}"))'
    assert steps.label_of(варианты) == "Ввод текста: один из 2 вариантов"


def test_account_text_never_goes_through_phrase():
    st = steps.normalize_step({"kind": "type", "args": {
        "value": "", "account": "vk", "field": "password"}})
    assert "phrase" not in codegen._call(st)
