import pytest

from edukit.feedback.effects import ALL_EFFECT_NAMES, EffectState, parse_color, render


def test_parse_color_forms():
    assert parse_color("green") == (0, 255, 0)
    assert parse_color("#ff8000") == (255, 128, 0)
    assert parse_color([300, -5, 7]) == (255, 0, 7)
    assert parse_color("bogus", (1, 2, 3)) == (1, 2, 3)


@pytest.mark.parametrize("name", ALL_EFFECT_NAMES)
def test_every_effect_renders(name):
    st = EffectState.from_command({"effect": name, "brightness": 255}, 0)
    for t in (0, 50, 500, 2500):
        px = render(st, t, 30)
        assert len(px) == 30 and all(0 <= c <= 255 for p in px for c in p)


def test_presets_resolve_to_expected_colours():
    st = EffectState.from_command({"effect": "correct", "brightness": 255}, 0)
    assert st.base == "wipe" and st.color == (0, 255, 0) and st.duration_ms == 3000
    assert render(st, 10_000, 10) == [(0, 255, 0)] * 10  # wipe completes to full green
    red = EffectState.from_command({"effect": "incorrect", "brightness": 255}, 0)
    assert red.color == (255, 0, 0)


def test_brightness_scales_output():
    st = EffectState.from_command({"effect": "solid", "color": "white", "brightness": 51}, 0)
    assert render(st, 0, 1) == [(51, 51, 51)]


def test_unknown_effect_raises():
    with pytest.raises(ValueError):
        EffectState.from_command({"effect": "lava-lamp"}, 0)


def test_expiry():
    st = EffectState.from_command({"effect": "solid", "duration_ms": 100}, 1000)
    assert not st.expired(1050) and st.expired(1100)
