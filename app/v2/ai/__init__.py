"""Unified AI provider layer (C1).

Adapters own provider-specific HTTP details; the service owns config, secrets,
default selection and the mobile platform gate. Business code never talks to a
provider SDK directly.
"""
from app.v2.ai.errors import AIError
from app.v2.ai.service import AIProviderService

__all__ = ["AIError", "AIProviderService"]
