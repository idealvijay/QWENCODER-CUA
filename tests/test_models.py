from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.geometry import Rect
from qwencoder_cua.models.result import ActionEffect, ActionResult


def test_ui_element_defaults():
    item = UIElement(id="e1", role="button", bounds=Rect(x=1, y=2, width=3, height=4))
    assert item.enabled is True
    assert item.actions == []


def test_action_result_serializes():
    result = ActionResult(
        success=False, effect=ActionEffect.UNVERIFIABLE,
        action_id="a1", message="No state check"
    )
    assert result.model_dump()["effect"] == "unverifiable"
