"""Theosis — a self-improving council engine where multiple AI models
draft, attack, repair, and merge into one answer."""
from .config import load_config
from .core import audit_pairs, theosis, theosis_stream
from .metrics import CompletionResult
from .models import MiddleLayer, ModelSlot

__all__ = ["ModelSlot", "MiddleLayer", "theosis", "theosis_stream", "audit_pairs", "load_config", "CompletionResult"]
__version__ = "2.14.0"
