from __future__ import annotations

import pytest

from qwencoder_cua.cli import _auto_paint_window_selector, _window_selector
from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.models.window import WindowInfo, WindowSelector


def _paint(window_id="42", title="Untitled - Paint", *, active=False, visible=True, minimized=False):
    return WindowInfo(
        id=window_id,
        title=title,
        process_id=4242,
        process_name="mspaint.exe",
        visible=visible,
        minimized=minimized,
        is_active=active,
    )


def test_auto_selects_paint_process_for_red_circle_goal():
    terminal = WindowInfo(
        id="10",
        title="Command Prompt",
        process_id=111,
        process_name="cmd.exe",
        is_active=True,
    )
    paint = _paint()

    selector = _auto_paint_window_selector(
        "Draw a red circle near the centre of the canvas and verify it.",
        [terminal, paint],
        terminal,
    )

    assert selector == WindowSelector(process_name="mspaint.exe")


def test_auto_selects_active_paint_window_when_multiple_are_open():
    first = _paint("42", "Untitled - Paint")
    second = _paint("43", "Drawing 2 - Paint", active=True)

    selector = _auto_paint_window_selector(
        "Draw a red circle on the canvas.",
        [first, second],
        second,
    )

    assert selector == WindowSelector(window_id="43")


def test_multiple_inactive_paint_windows_fail_safely():
    first = _paint("42", "Untitled - Paint")
    second = _paint("43", "Drawing 2 - Paint")

    with pytest.raises(CUAError, match="Multiple visible Microsoft Paint windows"):
        _auto_paint_window_selector(
            "Draw a circle.",
            [first, second],
            None,
        )


def test_auto_detection_ignores_hidden_and_minimized_paint_windows():
    hidden = _paint("42", visible=False)
    minimized = _paint("43", minimized=True)

    selector = _auto_paint_window_selector(
        "Draw a circle on the canvas.",
        [hidden, minimized],
        None,
    )

    assert selector is None


def test_non_drawing_goals_do_not_auto_target_paint():
    paint = _paint(active=True)

    selector = _auto_paint_window_selector(
        "Read the current window title.",
        [paint],
        paint,
    )

    assert selector is None


def test_explicit_window_options_remain_available_as_overrides():
    assert _window_selector("42", None, None) == WindowSelector(window_id="42")
    assert _window_selector(None, "notepad.exe", None) == WindowSelector(
        process_name="notepad.exe"
    )
    assert _window_selector(None, None, "Untitled") == WindowSelector(
        title_contains="Untitled"
    )
