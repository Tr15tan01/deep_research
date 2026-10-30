"""Server-side AI provider configuration: default/per-task models, fallback, allowed user
models, encrypted credentials, capability overrides and the timestamped pricing table.

Credentials precedence: a non-empty environment variable wins (ops-managed, read-only in
the UI); otherwise an administrator-stored key encrypted with ENCRYPTION_KEYS is used.
API keys are never returned to clients — only a masked suffix and their source.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret, utcnow
from app.db.mongo import Collections, col

PROVIDERS = ("gemini", "openai", "anthropic", "openai_compatible")
TASKS = ("planning", "extraction", "verification", "synthesis", "charts")
TaskName = Literal["planning", "extraction", "verification", "synthesis", "charts", "routine"]

SEARCH_KEY_PROVIDERS = ("firecrawl", "tavily", "brave")
_ENV_KEY = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
            "openai_compatible": "OPENAI_COMPATIBLE_API_KEY", "firecrawl": "FIRECRAWL_API_KEY",
            "tavily": "TAVILY_API_KEY", "brave": "BRAVE_SEARCH_API_KEY"}
CONFIG_ID = "ai_config"


class ModelRef(BaseModel):
    provider: Literal["gemini", "openai", "anthropic", "openai_compatible", "demo"]
    model: str = Field(min_length=1, max_length=200)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


class AllowedModel(ModelRef):
    label: str = ""


class PriceEntry(BaseModel):
    input_per_mtok_usd: float = Field(ge=0)
    output_per_mtok_usd: float = Field(ge=0)
    as_of: str = Field(description="Date the price was checked, e.g. 2026-10-01")
    source_note: str = ""


class CapabilityOverride(BaseModel):
    context_window: int | None = Field(default=None, ge=1024)
    max_output_tokens: int | None = Field(default=None, ge=256)
    supports_json_schema: bool | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    supports_temperature: bool | None = None
    supports_system_prompt: bool | None = None


class AIConfig(BaseModel):
    default: ModelRef | None = None
    tasks: dict[str, ModelRef | None] = Field(default_factory=dict)
    cheap: ModelRef | None = None
    fallback: ModelRef | None = None
    allowed_user_models: list[AllowedModel] = Field(default_factory=list)
    openai_compatible_base_url: str = ""
    capability_overrides: dict[str, CapabilityOverride] = Field(default_factory=dict)
    pricing: dict[str, PriceEntry] = Field(default_factory=dict)
    discovered: dict[str, dict[str, Any]] = Field(default_factory=dict)  # provider:model -> discovered limits


async def load_config() -> AIConfig:
    s = get_settings()
    doc = await col(Collections.app_settings).find_one({"_id": CONFIG_ID}) or {}
    data = {k: v for k, v in doc.items() if k in AIConfig.model_fields}
    cfg = AIConfig.model_validate(data)
    if cfg.default is None:
        if s.DEMO_MODE:
            cfg.default = ModelRef(provider="demo", model="demo-deterministic")
        elif s.AI_MODEL and s.AI_PROVIDER != "demo":
            cfg.default = ModelRef(provider=s.AI_PROVIDER, model=s.AI_MODEL)
    if not cfg.openai_compatible_base_url:
        cfg.openai_compatible_base_url = s.OPENAI_COMPATIBLE_BASE_URL
    return cfg


async def save_config(cfg: AIConfig, actor_id: str) -> None:
    body = cfg.model_dump(mode="json")
    body.update({"updated_at": utcnow(), "updated_by": actor_id})
    await col(Collections.app_settings).update_one({"_id": CONFIG_ID}, {"$set": body}, upsert=True)


async def _stored_credentials() -> dict[str, Any]:
    doc = await col(Collections.app_settings).find_one({"_id": "ai_credentials"}) or {}
    return doc.get("items", {})


async def get_api_key(provider: str) -> tuple[str, str]:
    """Returns (key, source) where source is environment | admin_store | none."""
    if provider == "demo":
        return "demo", "demo"
    env_name = _ENV_KEY.get(provider)
    env_val = getattr(get_settings(), env_name, "") if env_name else ""
    if env_val:
        return env_val, "environment"
    stored = (await _stored_credentials()).get(provider)
    if stored and stored.get("ciphertext"):
        return decrypt_secret(stored["ciphertext"], context=f"provider:{provider}"), "admin_store"
    return "", "none"


async def set_api_key(provider: str, api_key: str | None, actor_id: str) -> None:
    items = await _stored_credentials()
    if api_key:
        items[provider] = {"ciphertext": encrypt_secret(api_key, context=f"provider:{provider}"),
                           "last4": api_key[-4:], "updated_at": utcnow(), "updated_by": actor_id}
    else:
        items.pop(provider, None)
    await col(Collections.app_settings).update_one({"_id": "ai_credentials"}, {"$set": {"items": items}}, upsert=True)


async def credential_status(providers: tuple[str, ...] = PROVIDERS) -> dict[str, dict[str, Any]]:
    s = get_settings()
    stored = await _stored_credentials()
    out: dict[str, dict[str, Any]] = {}
    for p in providers:
        env_val = getattr(s, _ENV_KEY[p], "")
        if env_val:
            out[p] = {"configured": True, "source": "environment", "masked": "••••" + env_val[-4:]}
        elif p in stored:
            out[p] = {"configured": True, "source": "admin_store", "masked": "••••" + stored[p].get("last4", ""),
                      "updated_at": stored[p].get("updated_at")}
        else:
            out[p] = {"configured": False, "source": "none", "masked": ""}
    return out


# --- Per-user bring-your-own-key ---------------------------------------------------------------

async def get_user_api_key(user_id: str, provider: str) -> str | None:
    if not get_settings().ALLOW_USER_API_KEYS:
        return None
    doc = await col(Collections.user_api_credentials).find_one({"user_id": user_id, "provider": provider})
    if not doc:
        return None
    return decrypt_secret(doc["ciphertext"], context=f"user:{user_id}:provider:{provider}")


async def set_user_api_key(user_id: str, provider: str, api_key: str | None) -> None:
    from app.db.mongo import new_id

    c = col(Collections.user_api_credentials)
    if not api_key:
        await c.delete_one({"user_id": user_id, "provider": provider})
        return
    await c.update_one(
        {"user_id": user_id, "provider": provider},
        {"$set": {"ciphertext": encrypt_secret(api_key, context=f"user:{user_id}:provider:{provider}"),
                  "last4": api_key[-4:], "updated_at": utcnow()},
         "$setOnInsert": {"_id": new_id("cred"), "created_at": utcnow()}},
        upsert=True,
    )


# --- Search provider keys ------------------------------------------------------------------------
# Search keys may come from the environment or from the encrypted admin store (same storage as AI
# keys), so the API and every worker see a key saved once in Admin → AI providers. Search clients
# are built synchronously, so stored keys are decrypted into a short-lived in-process cache that
# async entry points refresh first (`await refresh_search_keys()`).

_search_keys: dict[str, str] = {}
_search_keys_at: float = 0.0
SEARCH_KEY_CACHE_SECONDS = 30.0


async def refresh_search_keys(force: bool = False) -> None:
    import time

    global _search_keys_at
    if not force and time.monotonic() - _search_keys_at < SEARCH_KEY_CACHE_SECONDS:
        return
    stored = await _stored_credentials()
    fresh: dict[str, str] = {}
    for p in SEARCH_KEY_PROVIDERS:
        item = stored.get(p)
        if item and item.get("ciphertext"):
            try:
                fresh[p] = decrypt_secret(item["ciphertext"], context=f"provider:{p}")
            except Exception as e:  # noqa: BLE001 — treated as missing; usually mismatched ENCRYPTION_KEYS
                from app.core.logging import get_logger

                get_logger("config").warning("search_key_undecryptable", provider=p, error=type(e).__name__)
    _search_keys.clear()
    _search_keys.update(fresh)
    _search_keys_at = time.monotonic()


def search_key(provider: str) -> str:
    """Environment value wins; otherwise the admin-stored key (from the last refresh)."""
    env_val = getattr(get_settings(), _ENV_KEY[provider], "")
    return env_val or _search_keys.get(provider, "")


def reset_search_key_cache() -> None:
    global _search_keys_at
    _search_keys.clear()
    _search_keys_at = 0.0
