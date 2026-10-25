"""Разрешение и плотность: разбор wm, команды, пропорции, сводка по телефонам."""
import pytest

from farm.control import display


def test_parse_wm_size_physical_only():
    assert display.parse_wm_size("Physical size: 1080x2400\n") == {
        "physical": (1080, 2400), "override": None, "current": (1080, 2400)}


def test_parse_wm_size_override_wins_as_current():
    got = display.parse_wm_size("Physical size: 1080x2400\nOverride size: 720x1600\n")
    assert got["physical"] == (1080, 2400)
    assert got["override"] == (720, 1600)
    assert got["current"] == (720, 1600)


def test_parse_wm_size_garbage_and_empty():
    for text in ("", None, "error: closed", "Physical size: ?x?"):
        assert display.parse_wm_size(text)["current"] is None


def test_parse_density():
    assert display.parse_density("Physical density: 420\n") == {
        "physical": 420, "override": None, "current": 420}
    got = display.parse_density("Physical density: 420\nOverride density: 320\n")
    assert got["current"] == 320 and got["physical"] == 420
    assert display.parse_density("")["current"] is None


def test_size_command_ok():
    assert display.size_command(720, 1600) == "wm size 720x1600"
    assert display.size_command("720", "1600.0") == "wm size 720x1600"


@pytest.mark.parametrize("w,h", [(100, 1600), (720, 100), (5000, 1600), (720, 9000), ("abc", 1)])
def test_size_command_rejects_out_of_range(w, h):
    with pytest.raises(ValueError) as e:
        display.size_command(w, h)
    assert "320" in str(e.value) and "4000" in str(e.value)


def test_density_command():
    assert display.density_command(320) == "wm density 320"
    for bad in (10, 5000, "x"):
        with pytest.raises(ValueError):
            display.density_command(bad)


def test_reset_commands():
    assert display.RESET_COMMANDS == ("wm size reset", "wm density reset")


def test_fit_height_keeps_ratio_and_is_even():
    assert display.fit_height(1080, 2400, 720) == 1600
    assert display.fit_height(1080, 2340, 720) == 1560
    assert display.fit_height(1080, 2401, 720) % 2 == 0


def test_summarize_groups_and_sorts():
    got = display.summarize([(1080, 2400), (720, 1600), (1080, 2400), None, (1080, 2400)])
    assert got == [{"size": (1080, 2400), "count": 3}, {"size": (720, 1600), "count": 1}]
    assert display.summarize([]) == []
