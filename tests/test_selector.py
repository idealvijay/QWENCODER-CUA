import pytest

from qwencoder_cua.core.exceptions import CUAError
from qwencoder_cua.core.selector import select_unique
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.selector import ElementSelector


def test_semantic_tool_selector_matches_clickable_windows_control():
    ellipse = UIElement(
        id="uia:7",
        role="button",
        name="Ellipse",
        enabled=True,
        visible=True,
        actions=["focus", "click"],
    )

    selected = select_unique(
        [ellipse],
        ElementSelector(role="tool", name="Ellipse/Oval"),
    )

    assert selected.id == "uia:7"


def test_semantic_tool_selector_matches_radio_button_and_oval_alias():
    oval = UIElement(
        id="uia:8",
        role="radio button",
        name="Oval",
        actions=["focus", "click"],
    )

    selected = select_unique(
        [oval],
        ElementSelector(role="tool", name="Ellipse/Oval"),
    )

    assert selected.id == "uia:8"


def test_semantic_tool_selector_rejects_non_clickable_element():
    label = UIElement(
        id="uia:9",
        role="text",
        name="Ellipse",
        enabled=True,
        visible=True,
        actions=["focus"],
    )

    with pytest.raises(CUAError, match="No element matched"):
        select_unique(
            [label],
            ElementSelector(role="tool", name="Ellipse/Oval"),
        )


def test_semantic_tool_selector_still_requires_unique_match():
    first = UIElement(
        id="uia:10", role="button", name="Ellipse",
        actions=["focus", "click"],
    )
    second = UIElement(
        id="uia:11", role="radio button", name="Oval",
        actions=["focus", "click"],
    )

    with pytest.raises(CUAError, match="matched 2 elements"):
        select_unique(
            [first, second],
            ElementSelector(role="tool", name="Ellipse/Oval"),
        )


def test_button_selector_matches_clickable_radio_button_with_combined_name():
    control = UIElement(
        id="uia:13",
        role="radio button",
        name="Ellipse/Oval",
        actions=["focus", "click"],
    )

    selected = select_unique(
        [control],
        ElementSelector(role="button", name="Ellipse"),
    )

    assert selected.id == "uia:13"


def test_ellipse_selector_matches_native_oval_name_case_insensitively():
    control = UIElement(
        id="uia:14",
        role="button",
        name="OVAL",
        actions=["focus", "click"],
    )

    selected = select_unique(
        [control],
        ElementSelector(role="tool", name="Ellipse"),
    )

    assert selected.id == "uia:14"


def test_button_alias_does_not_match_non_clickable_radio_button():
    control = UIElement(
        id="uia:15",
        role="radio button",
        name="Ellipse/Oval",
        actions=["focus"],
    )

    with pytest.raises(CUAError, match="No element matched"):
        select_unique(
            [control],
            ElementSelector(role="button", name="Ellipse"),
        )


def test_native_role_matching_remains_strict_for_non_button_roles():
    control = UIElement(
        id="uia:16",
        role="text",
        name="Ellipse",
        actions=["focus", "click"],
    )

    with pytest.raises(CUAError, match="No element matched"):
        select_unique(
            [control],
            ElementSelector(role="button", name="Ellipse"),
        )
