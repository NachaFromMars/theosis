"""Slot + middleware abstractions for Theosis."""
from __future__ import annotations

from typing import Callable, Optional


class MiddleLayer:
    """Per-slot middleware: a system prompt plus pre/post transforms.

    pre(request) -> str  : transform the prompt before it reaches the model
                           (inject persona, RAG context, reformatting, ...)
    post(output) -> str  : transform the raw model output (clean, extract, ...)

    Both default to pass-through. This is where each slot is customised
    independently without touching the orchestration core.
    """

    def __init__(
        self,
        system: Optional[str] = None,
        pre: Optional[Callable[[str], str]] = None,
        post: Optional[Callable[[str], str]] = None,
    ):
        self.system = system
        self._pre = pre or (lambda r: r)
        self._post = post or (lambda r: r)

    def pre(self, request: str) -> str:
        return self._pre(request)

    def post(self, output: str) -> str:
        return self._post(output)


class ModelSlot:
    """One pluggable model endpoint (OpenAI-compatible).

    base_url : API root ending in /v1; '/chat/completions' is appended.
               Use a 'mock://' URL to run the whole pipeline without a real
               provider (demo / tests / trying the UI).
    api_key  : provider key (ignored for mock slots).
    model    : model id exactly as that provider names it.
    """

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        api_key: str = "",
        middlelayer: Optional[MiddleLayer] = None,
        enabled: bool = True,
        runtime: bool = False,
    ):
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.middlelayer = middlelayer or MiddleLayer()
        self.enabled = enabled
        self.runtime = runtime  # True = thêm từ UI (lưu ở slots.local.yaml)

    @property
    def is_mock(self) -> bool:
        return self.base_url.startswith("mock")

    def __repr__(self) -> str:
        return f"ModelSlot(name={self.name!r}, model={self.model!r}, enabled={self.enabled})"
