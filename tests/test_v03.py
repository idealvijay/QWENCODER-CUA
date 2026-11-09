import pytest

from qwencoder_cua.accessibility.tokens import ElementTokenStore
from qwencoder_cua.core.exceptions import AmbiguousElementError, CUAError, StaleElementError
from qwencoder_cua.core.selector import select_unique
from qwencoder_cua.execution.verifier import verify_observation
from qwencoder_cua.models.element import UIElement
from qwencoder_cua.models.observation import Observation
from qwencoder_cua.models.selector import ElementSelector


def test_selector_requires_unique_match():
    elements = [UIElement(id="backend-1", role="button", name="Save", automation_id="save")]
    selected = select_unique(elements, ElementSelector(role="button", automation_id="save"))
    assert selected.id == "backend-1"


def test_ambiguous_selector_fails_closed():
    elements = [
        UIElement(id="1", role="button", name="OK"),
        UIElement(id="2", role="button", name="OK"),
    ]
    with pytest.raises(AmbiguousElementError):
        select_unique(elements, ElementSelector(role="button", name="OK"))


def test_empty_selector_is_rejected():
    with pytest.raises(CUAError):
        select_unique([], ElementSelector())


def test_token_store_restores_provider_id():
    store = ElementTokenStore()
    public = store.reset("observation-1", [UIElement(id="uia:17", role="button")])[0]
    assert public.id != "uia:17"
    assert store.resolve_provider_element(public.id).id == "uia:17"


def test_new_observation_invalidates_old_tokens():
    store = ElementTokenStore()
    old = store.reset("observation-1", [UIElement(id="atspi:1", role="button")])[0]
    store.reset("observation-2", [])
    with pytest.raises(StaleElementError):
        store.resolve(old.id)


def test_semantic_absence_verification_fails_closed_without_accessibility():
    observation = Observation(observation_id="o", platform="test", accessibility_available=False)
    verified, _ = verify_observation(
        observation, {"element_absent": {"role": "dialog", "name": "Confirm"}}
    )
    assert not verified


def test_active_window_verification_does_not_require_accessibility():
    from qwencoder_cua.models.window import WindowInfo
    observation = Observation(
        observation_id="o", platform="test",
        active_window=WindowInfo(id="1", title="Houdini - Scene"),
    )
    verified, _ = verify_observation(
        observation, {"active_window_title_contains": "Houdini"}
    )
    assert verified
