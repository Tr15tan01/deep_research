"""Model capability registry.

Capabilities are resolved in this order (later wins):
  1. Conservative provider defaults (documented assumptions, flagged as such).
  2. Limits discovered from the provider's model-listing API (when the provider reports them).
  3. Administrator overrides.

Model names are never hard-coded: administrators enter the exact model ID they want.
"""

from __future__ import annotations

from app.llm.base import ModelCapabilities
from app.llm.config_store import AIConfig, ModelRef

# Conservative defaults per provider API. These are deliberately cautious; the real limits
# vary per model and should be confirmed (discovery or admin override).
_PROVIDER_DEFAULTS: dict[str, ModelCapabilities] = {
    "openai": ModelCapabilities(context_window=128_000, max_output_tokens=8_192, supports_json_schema=True,
                                supports_tools=True, supports_streaming=True, supports_temperature=True,
                                notes=["Provider default — some reasoning models reject temperature; override if needed."]),
    "anthropic": ModelCapabilities(context_window=200_000, max_output_tokens=8_192, supports_json_schema=False,
                                   supports_tools=True, supports_streaming=True, supports_temperature=True,
                                   notes=["Structured output uses a forced tool call."]),
    "gemini": ModelCapabilities(context_window=1_000_000, max_output_tokens=8_192, supports_json_schema=True,
                                supports_tools=True, supports_streaming=True, supports_temperature=True,
                                notes=["Provider default; discovery reports exact token limits."]),
    "openai_compatible": ModelCapabilities(context_window=32_000, max_output_tokens=4_096, supports_json_schema=False,
                                           supports_tools=False, supports_streaming=True, supports_temperature=True,
                                           notes=["Unknown server: conservative defaults, JSON enforced by prompt + validation."]),
    "demo": ModelCapabilities(context_window=1_000_000, max_output_tokens=32_000, supports_json_schema=True,
                              supports_tools=True, supports_streaming=True, supports_temperature=True,
                              notes=["Deterministic demo provider — not a real model."]),
}


def resolve_capabilities(ref: ModelRef, cfg: AIConfig) -> ModelCapabilities:
    base = _PROVIDER_DEFAULTS.get(ref.provider, ModelCapabilities())
    caps = ModelCapabilities(**{k: getattr(base, k) for k in base.__dataclass_fields__ if k != "notes"},
                             notes=list(base.notes))
    caps.source = "default"
    disc = cfg.discovered.get(ref.key)
    if disc:
        if disc.get("context_window"):
            caps.context_window = int(disc["context_window"])
        if disc.get("max_output_tokens"):
            caps.max_output_tokens = int(disc["max_output_tokens"])
        caps.source = "discovered"
    ov = cfg.capability_overrides.get(ref.key)
    if ov:
        for k, v in ov.model_dump().items():
            if v is not None:
                setattr(caps, k, v)
        caps.source = "admin"
    return caps
