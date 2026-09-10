"""Compatibility shim — push adapters live in app.adapters.push."""

from app.adapters.push import PROVIDERS, PushProvider, register_push_provider

__all__ = ["PROVIDERS", "PushProvider", "register_push_provider"]
