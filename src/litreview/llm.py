from __future__ import annotations

import os

import anthropic

MODEL = os.environ.get("LITREVIEW_MODEL", "claude-opus-4-8")


def get_client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY (or an `ant auth login` profile) from the env.
    return anthropic.Anthropic()
