"""Theosis — a self-improving council engine where multiple AI models
draft, attack, repair, and merge into one answer."""
from .config import load_config
from .core import audit_pairs, theosis
from .metrics import CompletionResult
from .models import MiddleLayer, ModelSlot

__all__ = ["ModelSlot", "MiddleLayer", "theosis", "audit_pairs", "load_config", "CompletionResult"]
__version__ = "2.0.0"
