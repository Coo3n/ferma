"""Шаг «Ввести» из аккаунта телефона: ctx.account(...)[поле] вместо литерала."""
import pytest

from farm.recorder import codegen, steps


def _line(raw):
    return codegen.render({"name": "t"}, {}, [steps.normalize_step(raw)]).splitlines()[-1].strip()


def test_account_field_generates_lookup():
    assert _line({"kind": "type", "args": {"value": "x", "account": "vk", "field": "password",
                                           "clear": True}}) \
        == 'ctx.type(ctx.account("vk")["password"], clear=True)'


def test_plain_text_unchanged():
    assert _line({"kind": "type", "args": {"value": "hi"}}) == 'ctx.type("hi")'


def test_account_overrides_param():
    st = steps.normalize_step({"kind": "type", "param": "login",
                               "args": {"value": "x", "account": "tg", "field": "login"}})
    assert st["param"] is None


@pytest.mark.parametrize("args", [
    {"value": "x", "account": "fb", "field": "login"},
    {"value": "x", "account": "vk", "field": "email"},
])
def test_bad_account_rejected(args):
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "type", "args": args})
