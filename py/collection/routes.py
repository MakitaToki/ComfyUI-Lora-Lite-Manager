from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiohttp import web

from ..config import PLUGIN_ROOT
from .civitai_collector import CivitaiArtworkCollector
from .storage import COLLECTION_DIR, export_creative_seeds, get_artwork, search_artworks


def register_collection_routes(routes: Any, app: web.Application) -> None:
    routes.get("/collection-lite")(collection_page)
    routes.post("/api/lora-lite/collection/import")(import_collection)
    routes.get("/api/lora-lite/collection/items")(list_collection)
    routes.get("/api/lora-lite/collection/items/{artwork_id}")(get_collection_item)
    routes.get("/api/lora-lite/collection/image")(collection_image)
    routes.post("/api/lora-lite/collection/export-seeds")(export_collection_seeds)


async def collection_page(request: web.Request) -> web.Response:
    html_path = PLUGIN_ROOT / "static" / "collection.html"
    return web.FileResponse(html_path)


async def import_collection(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    url = str(payload.get("url", "") or "").strip()
    limit = int(payload.get("limit", 20) or 20)
    cache_images = bool(payload.get("cache_images", True))
    if not url:
        return web.json_response({"success": False, "error": "url is required"}, status=400)

    try:
        items = await CivitaiArtworkCollector().import_url(url, limit=limit, cache_images=cache_images)
        return web.json_response({"success": True, "items": items, "count": len(items)})
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=502)


async def list_collection(request: web.Request) -> web.Response:
    result = search_artworks(
        query=str(request.query.get("q", "") or ""),
        sort=str(request.query.get("sort", "newest") or "newest"),
        limit=int(request.query.get("limit", 60) or 60),
        offset=int(request.query.get("offset", 0) or 0),
    )
    return web.json_response({"success": True, **result})


async def get_collection_item(request: web.Request) -> web.Response:
    item = get_artwork(request.match_info.get("artwork_id", ""))
    if item is None:
        return web.json_response({"success": False, "error": "Artwork not found"}, status=404)
    return web.json_response({"success": True, "item": item})


async def collection_image(request: web.Request) -> web.StreamResponse:
    requested = str(request.query.get("path", "") or "")
    if not requested:
        raise web.HTTPNotFound()

    path = Path(requested).resolve()
    root = COLLECTION_DIR.resolve()
    if not _is_relative_to(path, root):
        raise web.HTTPForbidden(text="Image path is outside collection cache")
    if not path.exists() or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def export_collection_seeds(request: web.Request) -> web.Response:
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

    return web.json_response(
        {
            "success": True,
            "format": "lora_lite_creative_seeds.v1",
            "seeds": export_creative_seeds(items),
        },
        dumps=lambda value: json.dumps(value, ensure_ascii=False),
    )


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
