"""
Pytest configuration.

The openai-agents v0.8+ package installs as a namespace package (no top-level
__init__.py), so `from agents import Agent` fails at import time. Since the API
always calls extractors with use_ai_fallback=False, the agent code is never
executed during tests. Pre-populate sys.modules with a mock so the import chain
resolves without errors.
"""
from unittest.mock import MagicMock
import sys

for _mod in (
    "agents",
    "agents.agent",
    "agents.run",
    "agents.run_config",
    "agents.model_settings",
    "agents.models",
    "agents.models.openai_chatcompletions",
    "agents.mcp",
):
    sys.modules.setdefault(_mod, MagicMock())
