"""Pydantic model → JSON schema accepted by providers' strict structured-output mode.

Measured 2026-10-14: Groq rejects Pydantic's raw schema ("additionalProperties:false must be set
on every object", `$defs` not followed). So: inline `$ref`s, close every object, mark every
property required, and drop keywords strict mode does not support. Length/size constraints are
still enforced locally by Pydantic validation (with one repair round in the router).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

_DROP = {
    "$defs",
    "title",
    "default",
    "maxLength",
    "minLength",
    "minItems",
    "maxItems",
    "maximum",
    "minimum",
    "exclusiveMaximum",
    "exclusiveMinimum",
    "pattern",
    "format",
}


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
        out = {k: _inline(v, defs) for k, v in node.items() if k not in _DROP}
        if out.get("type") == "object" or "properties" in out:
            out["type"] = "object"
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out
    if isinstance(node, list):
        return [_inline(x, defs) for x in node]
    return node


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    return _inline(raw, raw.get("$defs", {}))
