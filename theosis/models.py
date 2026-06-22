"""Data models for Theosis slots and middleware."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class MiddleLayer:
    """Pre/post processing hooks for a model slot."""
    system: str = ""
    pre: Callable[[str], str] = field(default=lambda x: x)
    post: Callable[[str], str] = field(default=lambda x: x)


@dataclass
class ModelSlot:
    """One model endpoint participating in the Theosis council."""
    name: str
    model: str
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    enabled: bool = True
    is_mock: bool = False
    middlelayer: MiddleLayer = field(default_factory=MiddleLayer)

    @classmethod
    def mock(cls, name: str, model: str = "mock") -> "ModelSlot":
        """Convenience constructor for a mock slot (no API key needed)."""
        return cls(name=name, model=model, is_mock=True)
