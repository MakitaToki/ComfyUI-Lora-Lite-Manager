from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web

from ..collection.storage import get_artwork, search_artworks
from .matrix import build_experiment_cases
from .service import build_experiment_preview, create_run, get_run, list_runs, refresh_run, submit_run_step


def register_experiment_routes(routes: Any, app: web.Application) -> None:
    routes.get("/experiments-lite")(experiments_page)
    routes.post("/api/lora-lite/experiments/cases")(export_experiment_cases)
    routes.post("/api/lora-lite/experiments/preview")(preview_experiment)
    routes.post("/api/lora-lite/experiments/runs")(create_experiment_run)
    routes.get("/api/lora-lite/experiments/runs")(list_experiment_runs)
    routes.get("/api/lora-lite/experiments/runs/{run_id}")(get_experiment_run)
    routes.post("/api/lora-lite/experiments/runs/{run_id}/submit-step")(submit_experiment_run_step)
    routes.post("/api/lora-lite/experiments/runs/{run_id}/refresh")(refresh_experiment_run)


async def experiments_page(request: web.Request) -> web.Response:
    from ..config import PLUGIN_ROOT

    html_path = PLUGIN_ROOT / "static" / "experiments.html"
    return web.FileResponse(html_path)


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
        use_source_generation=bool(payload.get("use_source_generation", True)),
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


async def preview_experiment(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else payload
    preview = build_experiment_preview(recipe)
    return web.json_response({"success": True, "preview": preview}, dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def create_experiment_run(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else {}
    comfyui_url = str(payload.get("comfyui_url") or _origin_url(request) or "http://127.0.0.1:8188")
    submit = bool(payload.get("submit", True))
    try:
        run = await asyncio.to_thread(create_run, recipe, comfyui_url=comfyui_url, submit=submit)
        return web.json_response({"success": True, "run": run}, dumps=lambda value: json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=502)


async def list_experiment_runs(request: web.Request) -> web.Response:
    limit = int(request.query.get("limit", 50) or 50)
    return web.json_response({"success": True, "runs": list_runs(limit=limit)}, dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def get_experiment_run(request: web.Request) -> web.Response:
    run = get_run(request.match_info.get("run_id", ""))
    if run is None:
        return web.json_response({"success": False, "error": "Experiment run not found"}, status=404)
    return web.json_response({"success": True, "run": run}, dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def refresh_experiment_run(request: web.Request) -> web.Response:
    run = await asyncio.to_thread(refresh_run, request.match_info.get("run_id", ""))
    if run is None:
        return web.json_response({"success": False, "error": "Experiment run not found"}, status=404)
    return web.json_response({"success": True, "run": run}, dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def submit_experiment_run_step(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    batch_size = int(payload.get("batch_size", 1) or 1)
    try:
        run = await asyncio.to_thread(submit_run_step, request.match_info.get("run_id", ""), batch_size=batch_size)
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=502)
    if run is None:
        return web.json_response({"success": False, "error": "Experiment run not found"}, status=404)
    return web.json_response({"success": True, "run": run}, dumps=lambda value: json.dumps(value, ensure_ascii=False))


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _origin_url(request: web.Request) -> str:
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("Host", "")
    return f"{scheme}://{host}" if host else ""
