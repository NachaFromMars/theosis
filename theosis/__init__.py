"""Theosis — multi-model orchestration engine (fan-out → cross-audit → patch → merge)."""
from .core import theosis, EventCb
from .models import ModelSlot, MiddleLayer
from .prompts import MERGE_PROMPT, PATCH_SYS, RUBRIC

__version__ = "0.1.0"
__all__ = ["theosis", "EventCb", "ModelSlot", "MiddleLayer", "MERGE_PROMPT", "PATCH_SYS", "RUBRIC"]
