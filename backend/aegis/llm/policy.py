"""LLM policy for the bounded tool controller (engine/controller.py).

The model receives only the controller context (agent-side observations and tool results) and must answer with one
JSON tool call. Output is schema-validated; anything else raises PolicyError and the controller falls back to the
deterministic agent. Requires ANTHROPIC_API_KEY; not verified against a live model in the build environment.
"""
from __future__ import annotations

import json
import os
import re

import httpx
from pydantic import ValidationError

from ..engine.controller import PolicyError, ToolCall

MODEL = os.environ.get("AEGIS_LLM_MODEL", "claude-haiku-5-5")
def _timeout(raw: str | None, default: float = 10.0) -> float:
    """Validated LLM timeout in seconds: invalid, non-finite or out-of-range values fall back to the default."""
    try:
        v = float(raw) if raw is not None else default
    except ValueError:
        return default
    return v if 0.5 <= v <= 60 else default


TIMEOUT_S = _timeout(os.environ.get("AEGIS_LLM_TIMEOUT"))
SYSTEM = ("You are the decision controller of AEGIS, an infrastructure-recovery agent running in a SIMULATION. "
          "Choose exactly one next tool from `tools`. Use only facts in the context. The safety gate, approval "
          "requirements and executor checks are enforced by code and cannot be bypassed; propose only plans whose "
          "gate status is PASSED, or abstain. Reply with JSON only: "
          '{"tool": "<name>", "args": {...}, "reason": "<short reason>"}')


class LLMPolicy:
    name = "llm"

    def __init__(self, client: httpx.Client | None = None, model: str = MODEL, api_key: str | None = None):
        self.client, self.model = client, model
        self.key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def next_call(self, context: dict) -> ToolCall:
        if not self.key:
            raise PolicyError("no API key")
        try:
            cl = self.client or httpx.Client(timeout=TIMEOUT_S)
            r = cl.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": self.model, "max_tokens": 300, "system": SYSTEM,
                      "messages": [{"role": "user", "content": json.dumps(context)[:20000]}]})
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        except httpx.HTTPError as e:
            raise PolicyError(f"LLM request failed: {type(e).__name__}") from None
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise PolicyError("LLM reply contained no JSON tool call")
        try:
            return ToolCall.model_validate(json.loads(m.group(0)))
        except (ValidationError, json.JSONDecodeError) as e:
            raise PolicyError(f"invalid tool call: {str(e)[:120]}") from None
