"""Account, templates, library, notifications, usage and user-facing model settings."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.auth.deps import Principal, clear_auth_cookies, current_principal
from app.auth.service import public_user, verify_password
from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.security import utcnow
from app.db.mongo import Collections, aggregate, col, new_id
from app.llm.config_store import PROVIDERS, load_config, set_user_api_key
from app.research.modes import MODES
from app.services import account as account_svc
from app.services.audit import audit
from app.services.limits import usage_snapshot

router = APIRouter(prefix="/api/v1", tags=["user"])


# --- Account ------------------------------------------------------------------------------------

class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    preferences: dict[str, Any] | None = None


class DeleteAccountIn(BaseModel):
    password: str | None = Field(default=None, max_length=256)
    confirm: str = Field(max_length=40)


@router.patch("/account/profile")
async def update_profile(body: ProfileIn, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    upd: dict[str, Any] = {"updated_at": utcnow()}
    if body.name is not None:
        upd["name"] = body.name.strip()
    if body.preferences is not None:
        allowed = {"theme", "default_mode", "reduced_motion", "email_notifications"}
        prefs = {k: v for k, v in body.preferences.items() if k in allowed and isinstance(v, (str, bool, int))}
        upd["preferences"] = {**principal.user.get("preferences", {}), **prefs}
    await col(Collections.users).update_one({"_id": principal.id}, {"$set": upd})
    user = await col(Collections.users).find_one({"_id": principal.id})
    return {"user": public_user(user)}


@router.get("/account/export")
async def export_account(request: Request, principal: Principal = Depends(current_principal)) -> JSONResponse:
    await ratelimit.enforce(ratelimit.AUTH_EMAIL, f"export:{principal.id}")
    data = await account_svc.export_user_data(principal.id)
    await audit("account.exported", actor_id=principal.id, ip=ratelimit.client_ip(request))
    import json

    return JSONResponse(json.loads(json.dumps(data, default=str)),
                        headers={"Content-Disposition": 'attachment; filename="deep-research-export.json"'})


@router.post("/account/delete")
async def delete_account(body: DeleteAccountIn, request: Request, response: Response,
                         principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    if body.confirm != "DELETE":
        raise AppError('Type DELETE to confirm.', code="confirmation_required", status_code=422)
    if principal.user.get("password_hash") and not verify_password(body.password or "", principal.user["password_hash"]):
        raise AppError("Password is incorrect.", code="invalid_credentials", status_code=400)
    await audit("account.deleted", actor_id=principal.id, ip=ratelimit.client_ip(request))
    await account_svc.delete_account(principal.id)
    clear_auth_cookies(response)
    return {"deleted": True}


# --- Usage --------------------------------------------------------------------------------------

@router.get("/usage")
async def usage(principal: Principal = Depends(current_principal), days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    snap = await usage_snapshot(principal.user)
    by_day = await aggregate(col(Collections.usage_records), [
        {"$match": {"user_id": principal.id, "created_at": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "llm_calls": {"$sum": {"$cond": [{"$eq": ["$kind", "llm"]}, 1, 0]}},
                    "search_calls": {"$sum": {"$cond": [{"$eq": ["$kind", "search"]}, 1, 0]}},
                    "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                    "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                    "cost": {"$sum": {"$ifNull": ["$cost_usd_est", 0]}}}},
        {"$sort": {"_id": 1}},
    ])
    jobs = await col(Collections.research_jobs).find({"user_id": principal.id, "kind": "research", "created_at": {"$gte": since}},
                                                     {"question": 1, "usage": 1, "status": 1, "created_at": 1, "mode": 1}
                                                     ).sort("created_at", -1).limit(50).to_list(None)
    return {"snapshot": snap, "by_day": [{"day": r["_id"], **{k: v for k, v in r.items() if k != "_id"}} for r in by_day],
            "jobs": [{"id": j["_id"], "question": j["question"], "status": j["status"], "mode": j.get("mode"),
                      "created_at": j["created_at"], "usage": j.get("usage", {})} for j in jobs]}


# --- Model choices & BYOK -----------------------------------------------------------------------

class UserKeyIn(BaseModel):
    provider: str
    api_key: str | None = Field(default=None, max_length=500)


@router.get("/models")
async def user_models(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    s = get_settings()
    cfg = await load_config()
    own = []
    if s.ALLOW_USER_API_KEYS:
        own = [{"provider": d["provider"], "masked": "••••" + d.get("last4", "")}
               for d in await col(Collections.user_api_credentials).find({"user_id": principal.id}).to_list(None)]
    return {"selection_enabled": s.ALLOW_USER_MODEL_SELECTION, "byok_enabled": s.ALLOW_USER_API_KEYS,
            "default": cfg.default.model_dump() if cfg.default else None,
            "allowed": [m.model_dump() for m in cfg.allowed_user_models] if s.ALLOW_USER_MODEL_SELECTION else [],
            "own_keys": own, "demo_mode": s.DEMO_MODE}


@router.put("/models/own-key")
async def set_own_key(body: UserKeyIn, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    if not get_settings().ALLOW_USER_API_KEYS:
        raise AppError("Bring-your-own-key is disabled.", code="feature_disabled", status_code=404)
    if body.provider not in PROVIDERS or body.provider == "openai_compatible":
        raise AppError("Unsupported provider.", code="invalid_provider", status_code=422)
    await set_user_api_key(principal.id, body.provider, body.api_key)
    await audit("user.api_key_updated", actor_id=principal.id, ip=ratelimit.client_ip(request),
                metadata={"provider": body.provider, "removed": not body.api_key})
    return {"saved": True}


# --- Templates ----------------------------------------------------------------------------------

class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    question_template: str = Field(min_length=8, max_length=4000)
    mode: str = "standard"
    options: dict[str, Any] = Field(default_factory=dict)


SYSTEM_TEMPLATES = [
    {"id": "tpl_sys_vendor", "name": "Vendor comparison", "mode": "competitive",
     "description": "Compare vendors on price, features and limitations with a cited matrix.",
     "question_template": "Compare {vendor A} and {vendor B} for {use case}: pricing, key features, limitations and customer adoption."},
    {"id": "tpl_sys_market", "name": "Market sizing", "mode": "market",
     "description": "Market size, growth and key players, with charts where data allows.",
     "question_template": "What is the size and growth rate of the {market} market in {region}, and who are the leading players?"},
    {"id": "tpl_sys_tech", "name": "Technology choice", "mode": "technology",
     "description": "Evaluate technical options for a decision.",
     "question_template": "Should a team building {product} choose {option A} or {option B}? Compare performance, ecosystem, cost and risks."},
    {"id": "tpl_sys_lit", "name": "Literature review", "mode": "academic",
     "description": "Scholarly overview of the evidence on a question.",
     "question_template": "What does recent research say about {topic}? Summarise findings, methods and open questions."},
    {"id": "tpl_sys_claim", "name": "Verify a claim", "mode": "verify_claim",
     "description": "Find evidence for and against a specific claim.",
     "question_template": "Is it true that {claim}? Find the original source and evidence for and against."},
    {"id": "tpl_sys_policy", "name": "Policy brief", "mode": "standard",
     "description": "Neutral overview of a policy question with stakeholder positions.",
     "question_template": "What are the effects of {policy} in {place}, and what do supporters and critics argue?"},
]


@router.get("/templates")
async def list_templates(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    mine = await col(Collections.research_templates).find({"user_id": principal.id}).sort("created_at", -1).to_list(None)
    return {"system": SYSTEM_TEMPLATES,
            "mine": [{"id": t["_id"], **{k: t.get(k) for k in ("name", "description", "question_template", "mode", "options",
                                                                 "created_at", "uses")}} for t in mine]}


@router.post("/templates", status_code=201)
async def create_template(body: TemplateIn, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    if body.mode not in MODES:
        raise AppError("Unknown mode.", code="invalid_mode", status_code=422)
    if await col(Collections.research_templates).count_documents({"user_id": principal.id}) >= 200:
        raise AppError("Template limit reached.", code="limit", status_code=409)
    allowed_opts = {"include_domains", "exclude_domains", "source_preferences", "language", "review_plan"}
    doc = {"_id": new_id("tpl"), "user_id": principal.id, **body.model_dump(exclude={"options"}),
           "options": {k: v for k, v in body.options.items() if k in allowed_opts}, "uses": 0, "created_at": utcnow()}
    await col(Collections.research_templates).insert_one(doc)
    return {"id": doc["_id"]}


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    res = await col(Collections.research_templates).delete_one({"_id": template_id, "user_id": principal.id})
    if not res.deleted_count:
        raise NotFound("Template not found.")
    return {"deleted": True}


# --- Library ------------------------------------------------------------------------------------

class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)


class LibraryItemIn(BaseModel):
    kind: str = Field(pattern="^(report|source)$")
    ref_id: str = Field(max_length=40)
    job_id: str | None = Field(default=None, max_length=40)
    collection_ids: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=2000)


@router.get("/library")
async def library(principal: Principal = Depends(current_principal), q: str | None = Query(default=None, max_length=200),
                  tag: str | None = None, collection_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {"user_id": principal.id}
    if tag:
        query["tags"] = tag
    if collection_id:
        query["collection_ids"] = collection_id
    if kind:
        query["kind"] = kind
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"title": rx}, {"note": rx}, {"tags": rx}, {"domain": rx}]
    items = await col(Collections.library_items).find(query).sort("created_at", -1).limit(300).to_list(None)
    cols = await col(Collections.library_collections).find({"user_id": principal.id}).sort("name", 1).to_list(None)
    tags = sorted({t for i in await col(Collections.library_items).find({"user_id": principal.id}, {"tags": 1}).to_list(None)
                   for t in i.get("tags", [])})
    return {"items": [{"id": i["_id"], **{k: i.get(k) for k in ("kind", "ref_id", "job_id", "title", "url", "domain", "tags",
                                                                  "collection_ids", "note", "created_at", "source_type",
                                                                  "published_at", "duplicates")}} for i in items],
            "collections": [{"id": c["_id"], "name": c["name"], "description": c.get("description", "")} for c in cols],
            "tags": tags}


@router.post("/library/collections", status_code=201)
async def create_collection(body: CollectionIn, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    doc = {"_id": new_id("lcol"), "user_id": principal.id, "name": body.name.strip(), "description": body.description,
           "created_at": utcnow()}
    await col(Collections.library_collections).insert_one(doc)
    return {"id": doc["_id"]}


@router.delete("/library/collections/{collection_id}")
async def delete_collection(collection_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    await col(Collections.library_collections).delete_one({"_id": collection_id, "user_id": principal.id})
    await col(Collections.library_items).update_many({"user_id": principal.id}, {"$pull": {"collection_ids": collection_id}})
    return {"deleted": True}


@router.post("/library/items", status_code=201)
async def save_item(body: LibraryItemIn, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    from app.search.canonical import canonicalize_url

    if body.collection_ids:
        n = await col(Collections.library_collections).count_documents({"_id": {"$in": body.collection_ids}, "user_id": principal.id})
        if n != len(set(body.collection_ids)):
            raise NotFound("Collection not found.")
    meta: dict[str, Any] = {}
    if body.kind == "report":
        job = await col(Collections.research_jobs).find_one({"_id": body.ref_id, "user_id": principal.id})
        if not job:
            raise NotFound("Research not found.")
        meta = {"title": job.get("title") or job["question"], "job_id": job["_id"]}
    else:
        src = await col(Collections.research_sources).find_one({"_id": body.ref_id, "user_id": principal.id})
        if not src:
            raise NotFound("Source not found.")
        canonical = src["canonical_url"]
        dup = await col(Collections.library_items).find_one({"user_id": principal.id, "kind": "source", "canonical_url": canonical})
        if dup:
            await col(Collections.library_items).update_one(
                {"_id": dup["_id"]}, {"$addToSet": {"duplicates": body.ref_id, "collection_ids": {"$each": body.collection_ids},
                                                     "tags": {"$each": body.tags}}})
            return {"id": dup["_id"], "deduplicated": True}
        meta = {"title": src.get("title") or src["url"], "url": src["url"], "canonical_url": canonicalize_url(src["url"]),
                "domain": src.get("domain"), "job_id": src["job_id"], "source_type": src.get("source_type"),
                "published_at": src.get("published_at")}
    doc = {"_id": new_id("lib"), "user_id": principal.id, "kind": body.kind, "ref_id": body.ref_id,
           "collection_ids": body.collection_ids, "tags": [t.strip()[:40] for t in body.tags if t.strip()], "note": body.note,
           "created_at": utcnow(), **meta}
    try:
        await col(Collections.library_items).insert_one(doc)
    except DuplicateKeyError as e:
        raise Conflict("Already in your library.") from e
    return {"id": doc["_id"]}


@router.patch("/library/items/{item_id}")
async def update_item(item_id: str, body: dict[str, Any], principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    upd: dict[str, Any] = {}
    if "tags" in body and isinstance(body["tags"], list):
        upd["tags"] = [str(t).strip()[:40] for t in body["tags"][:20] if str(t).strip()]
    if "note" in body:
        upd["note"] = str(body["note"])[:2000]
    if "collection_ids" in body and isinstance(body["collection_ids"], list):
        ids = [str(c) for c in body["collection_ids"][:20]]
        n = await col(Collections.library_collections).count_documents({"_id": {"$in": ids}, "user_id": principal.id})
        if n != len(set(ids)):
            raise NotFound("Collection not found.")
        upd["collection_ids"] = ids
    res = await col(Collections.library_items).update_one({"_id": item_id, "user_id": principal.id}, {"$set": upd})
    if not res.matched_count:
        raise NotFound("Item not found.")
    return {"updated": True}


@router.delete("/library/items/{item_id}")
async def delete_item(item_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    await col(Collections.library_items).delete_one({"_id": item_id, "user_id": principal.id})
    return {"deleted": True}


@router.get("/library/related/{job_id}")
async def related_reports(job_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    """Reports that share sources (by canonical URL) with this one — a factual relationship."""
    mine = await col(Collections.research_sources).find({"job_id": job_id, "user_id": principal.id}, {"canonical_url": 1}).to_list(None)
    urls = [s["canonical_url"] for s in mine]
    if not urls:
        return {"items": []}
    rows = await aggregate(col(Collections.research_sources), [
        {"$match": {"user_id": principal.id, "canonical_url": {"$in": urls}, "job_id": {"$ne": job_id}}},
        {"$group": {"_id": "$job_id", "shared": {"$sum": 1}}}, {"$sort": {"shared": -1}}, {"$limit": 10}])
    out = []
    for r in rows:
        j = await col(Collections.research_jobs).find_one({"_id": r["_id"], "user_id": principal.id}, {"question": 1, "title": 1, "created_at": 1})
        if j:
            out.append({"job_id": j["_id"], "title": j.get("title") or j["question"], "shared_sources": r["shared"],
                        "created_at": j["created_at"], "relationship": "shares sources"})
    return {"items": out}


# --- Notifications ------------------------------------------------------------------------------

@router.get("/notifications")
async def notifications(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    items = await col(Collections.notifications).find({"user_id": principal.id}).sort("created_at", -1).limit(50).to_list(None)
    unread = await col(Collections.notifications).count_documents({"user_id": principal.id, "read": False})
    return {"items": [{"id": n["_id"], **{k: n.get(k) for k in ("kind", "title", "body", "link", "read", "created_at")}}
                      for n in items], "unread": unread}


@router.post("/notifications/read-all")
async def read_all(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    res = await col(Collections.notifications).update_many({"user_id": principal.id, "read": False}, {"$set": {"read": True}})
    return {"updated": res.modified_count}
