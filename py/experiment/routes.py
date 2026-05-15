from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from ..collection.storage import get_artwork, search_artworks
from .matrix import build_experiment_cases


def register_experiment_routes(routes: Any, app: web.Application) -> None:
    routes.post("/api/lora-lite/experiments/cases")(export_experiment_cases)


async def export_experiment_cases(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    ids = payload.get("ids")
    if isinstance(ids, list) and ids:
        items = [item for item_id in ids if (item := get_artwork(str(item_id)))]
    else:
        result = search_artworks(
            query=str(payload.get("query", "") or ""),
            sort=str(payload.get("sort", "popular") or "popular"),
            limit=int(payload.get("limit", 100) or 100),
        )
        items = result["items"]

    cases = build_experiment_cases(
        items,
        title_prefix=str(payload.get("title_prefix", "lora_lite_exp") or "lora_lite_exp"),
        workflow_profile=str(payload.get("workflow_profile", "advanced_v34") or "advanced_v34"),
        checkpoint=str(payload.get("checkpoint", "") or ""),
        loras=payload.get("loras") if isinstance(payload.get("loras"), list) else None,
        use_source_loras=bool(payload.get("use_source_loras", False)),
        generation_defaults=payload.get("generation_defaults") if isinstance(payload.get("generation_defaults"), dict) else None,
    )
    return web.json_response(
        {
            "success": True,
            "format": "lora_lite_experiment_cases.v1",
            "cases": cases,
            "summary": {
                "total": len(cases),
                "ready": sum(1 for case in cases if case.get("compile_status") == "ready"),
                "draft": sum(1 for case in cases if case.get("compile_status") != "ready"),
            },
        },
        dumps=lambda value: json.dumps(value, ensure_ascii=False),
    )


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
