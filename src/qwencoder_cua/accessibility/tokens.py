from __future__ import annotations
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4
from qwencoder_cua.core.exceptions import StaleElementError
from qwencoder_cua.models.element import UIElement

@dataclass
class _Entry:
    element: UIElement
    backend_id: str
    expires_at: float

class ElementTokenStore:
    """Short-lived public tokens mapped to provider-local IDs."""
    def __init__(self, ttl_seconds: float = 15.0):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, _Entry] = {}
        self.observation_id: str | None = None

    def reset(self, observation_id: str, elements: list[UIElement]) -> list[UIElement]:
        self.observation_id = observation_id
        self._entries.clear()
        now = monotonic()
        mapped = []
        for source in elements:
            token = uuid4().hex
            element = source.model_copy(update={"id": token})
            self._entries[token] = _Entry(element, source.id, now + self.ttl_seconds)
            mapped.append(element)
        return mapped

    def _get(self, token: str) -> _Entry:
        entry = self._entries.get(token)
        if entry is None or monotonic() > entry.expires_at:
            self._entries.pop(token, None)
            raise StaleElementError("Element token is unknown or expired. Call observe() again.")
        return entry

    def resolve(self, token: str) -> UIElement:
        return self._get(token).element

    def resolve_provider_element(self, token: str) -> UIElement:
        entry = self._get(token)
        return entry.element.model_copy(update={"id": entry.backend_id})

    def elements(self) -> list[UIElement]:
        now = monotonic()
        for token in [k for k, e in self._entries.items() if now > e.expires_at]:
            self._entries.pop(token, None)
        return [e.element for e in self._entries.values()]
