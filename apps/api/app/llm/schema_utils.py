"""JSON-schema helpers for structured outputs across providers."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from pydantic import BaseModel


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Dereference local ``$defs`` references (non-recursive schemas only)."""
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {}) or schema.pop("definitions", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 30:
            return {}
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                name = node["$ref"].split("/")[-1]
                target = copy.deepcopy(defs.get(name, {}))
                merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
                return resolve(merged, depth + 1)
            return {k: resolve(v, depth + 1) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v, depth + 1) for v in node]
        return node

    return resolve(schema)


def model_schema(model: type[BaseModel]) -> dict[str, Any]:
    return inline_refs(model.model_json_schema())


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Parse JSON from model text, tolerating code fences and surrounding prose."""
    t = text.strip()
    t = _FENCE.sub("", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    # Find the first balanced JSON object/array.
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = t.find(open_ch)
        while start != -1:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(t)):
                c = t[i]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == open_ch:
                    depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(t[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = t.find(open_ch, start + 1)
    raise ValueError("no JSON value found in model output")
