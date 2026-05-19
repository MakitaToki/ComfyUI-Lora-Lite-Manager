from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from aiohttp import web

from .civitai import CIVITAI_DOWNLOAD_PREFIX, CivitaiClient, normalize_download_url, select_model_file
from .config import PLUGIN_ROOT, get_default_lora_root, get_lora_roots, load_config, read_settings, write_settings
from .downloader import Downloader
from .metadata import PREVIEW_EXTENSIONS, calculate_sha256, load_metadata, metadata_path_for, normalize_path, save_metadata
from .scanner import find_lora_by_path, scan_loras


def register_routes() -> None:
    try:
        from server import PromptServer  # type: ignore
    except Exception:
        return

    routes = PromptServer.instance.routes
    app = PromptServer.instance.app
    _add_static_route(app, "/lora-lite-static", PLUGIN_ROOT / "static")

    routes.get("/lora-lite")(lora_lite_page)
    routes.get("/recipe-lite")(recipe_lite_page)
    routes.get("/api/lora-lite/roots")(get_roots)
    routes.get("/api/lora-lite/settings")(get_settings)
    routes.post("/api/lora-lite/settings")(update_settings)
    routes.post("/api/lora-lite/settings/test-civitai")(test_civitai_settings)
    routes.get("/api/lora-lite/loras")(list_loras)
    routes.post("/api/lora-lite/scan")(scan_loras_route)
    routes.post("/api/lora-lite/hash")(hash_lora)
    routes.get("/api/lora-lite/preview")(preview_file)
    routes.get("/api/lora-lite/civitai/by-hash/{sha256}")(civitai_by_hash)
    routes.post("/api/lora-lite/metadata")(update_metadata)
    routes.post("/api/lora-lite/delete")(delete_lora)
    routes.post("/api/lora-lite/download")(download_lora)

    from .collection.routes import register_collection_routes

    register_collection_routes(routes, app)

    from .experiment.routes import register_experiment_routes

    register_experiment_routes(routes, app)


async def lora_lite_page(request: web.Request) -> web.Response:
    html_path = PLUGIN_ROOT / "static" / "index.html"
    return _html_response(html_path)


async def recipe_lite_page(request: web.Request) -> web.Response:
    html_path = PLUGIN_ROOT / "static" / "recipe.html"
    return _html_response(html_path)


async def get_roots(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "success": True,
            "roots": get_lora_roots(),
            "default_root": get_default_lora_root(),
        }
    )


async def get_settings(request: web.Request) -> web.Response:
    config = load_config()
    settings = read_settings()
    return web.json_response(
        {
            "success": True,
            "settings": {
                "civitai_api_key": config.civitai_api_key,
                "has_civitai_api_key": bool(config.civitai_api_key),
                "api_key_source": _api_key_source(settings),
            },
        }
    )


async def update_settings(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    settings = read_settings()
    if "civitai_api_key" in payload:
        settings["civitai_api_key"] = str(payload.get("civitai_api_key", "") or "").strip()
    write_settings(settings)
    return await get_settings(request)


async def test_civitai_settings(request: web.Request) -> web.Response:
    try:
        await CivitaiClient().get_model_version(2432252)
        return web.json_response({"success": True})
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=502)


async def list_loras(request: web.Request) -> web.Response:
    return web.json_response({"success": True, "items": scan_loras()})


async def scan_loras_route(request: web.Request) -> web.Response:
    return await list_loras(request)


async def hash_lora(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    file_path = str(payload.get("file_path", "") or "")
    record = find_lora_by_path(file_path)
    if record is None:
        return web.json_response({"success": False, "error": "LoRA file not found"}, status=404)

    sha256 = await calculate_sha256(record["file_path"])
    metadata = load_metadata(record["file_path"])
    metadata["sha256"] = sha256
    save_metadata(record["file_path"], metadata)
    return web.json_response({"success": True, "sha256": sha256})


async def preview_file(request: web.Request) -> web.StreamResponse:
    requested = str(request.query.get("path", "") or "")
    if not requested:
        raise web.HTTPNotFound()

    path = Path(requested).resolve()
    allowed = [Path(root).resolve() for root in get_lora_roots()]
    if not any(_is_relative_to(path, root) for root in allowed):
        raise web.HTTPForbidden(text="Preview path is outside configured LoRA roots")
    if not path.exists() or not path.is_file():
        raise web.HTTPNotFound()

    return web.FileResponse(path)


async def civitai_by_hash(request: web.Request) -> web.Response:
    sha256 = request.match_info.get("sha256", "").strip()
    if not sha256:
        return web.json_response({"success": False, "error": "sha256 is required"}, status=400)

    try:
        result = await CivitaiClient().get_model_by_hash(sha256)
        return web.json_response({"success": True, "result": result})
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=502)


async def update_metadata(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    file_path = str(payload.get("file_path", "") or "")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return web.json_response({"success": False, "error": "metadata object is required"}, status=400)

    record = find_lora_by_path(file_path)
    if record is None:
        return web.json_response({"success": False, "error": "LoRA file not found"}, status=404)

    save_metadata(record["file_path"], metadata)
    return web.json_response({"success": True, "metadata": load_metadata(record["file_path"])})


async def delete_lora(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    file_path = str(payload.get("file_path", "") or "")
    record = find_lora_by_path(file_path)
    if record is None:
        return web.json_response({"success": False, "error": "LoRA file not found"}, status=404)

    model_path = Path(record["file_path"]).resolve()
    allowed_roots = [Path(root).resolve() for root in get_lora_roots()]
    if not any(_is_relative_to(model_path, root) for root in allowed_roots):
        return web.json_response({"success": False, "error": "LoRA file is outside configured roots"}, status=403)

    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for path in _delete_candidates(model_path):
        if not path.exists() or not path.is_file():
            continue
        try:
            path.unlink()
            deleted.append(normalize_path(path))
        except OSError as exc:
            failed.append({"path": normalize_path(path), "error": str(exc)})

    if failed:
        return web.json_response({"success": False, "deleted": deleted, "failed": failed}, status=500)
    return web.json_response({"success": True, "deleted": deleted})


async def download_lora(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    model_version_id = payload.get("model_version_id")
    model_id = payload.get("model_id")
    if model_version_id is None and model_id is None:
        return web.json_response({"success": False, "error": "model_version_id or model_id is required"}, status=400)

    save_root = str(payload.get("save_root") or get_default_lora_root())
    if not save_root:
        return web.json_response({"success": False, "error": "No LoRA root is configured"}, status=400)

    try:
        client = CivitaiClient()
        version = await _download_version_from_payload(client, payload)
        file_info = select_model_file(version, payload.get("file_params"))
        if not file_info:
            return web.json_response({"success": False, "error": "No downloadable model file found"}, status=404)

        file_name = file_info.get("name") or f"{model_version_id}.safetensors"
        relative_dir = str(payload.get("relative_dir", "") or "").strip("/\\")
        save_dir = Path(save_root) / relative_dir
        save_path = _unique_path(save_dir / file_name)

        download_url = file_info.get("downloadUrl") or f"{CIVITAI_DOWNLOAD_PREFIX}{model_version_id}"
        download_url = normalize_download_url(str(download_url))
        result_path = await Downloader().download_file(
            download_url,
            save_path,
            use_auth=True,
            expected_size=_file_size_bytes(file_info),
        )

        metadata = _metadata_from_version(version, file_info, result_path)
        save_metadata(result_path, metadata)
        return web.json_response(
            {
                "success": True,
                "file_path": normalize_path(result_path),
                "metadata": metadata,
            }
        )
    except Exception as exc:
        return web.json_response({"success": False, "error": str(exc)}, status=502)


async def _download_version_from_payload(client: CivitaiClient, payload: dict[str, Any]) -> dict[str, Any]:
    model_version_id = payload.get("model_version_id")
    if model_version_id is not None:
        return await client.get_model_version(int(model_version_id))

    model_id = int(payload.get("model_id"))
    model = await client.get_model(model_id)
    versions = model.get("modelVersions")
    if not isinstance(versions, list) or not versions:
        raise ValueError(f"No model versions found for Civitai model {model_id}.")
    preferred_base = str(payload.get("preferred_base_model") or "").lower()
    candidates = [version for version in versions if isinstance(version, dict)]
    if preferred_base:
        matched = [version for version in candidates if preferred_base in str(version.get("baseModel") or "").lower()]
        if matched:
            candidates = matched
    published = [version for version in candidates if str(version.get("status") or "").lower() in {"published", ""}]
    candidates = published or candidates
    return candidates[0]


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _file_size_bytes(file_info: dict[str, Any]) -> int | None:
    size_kb = file_info.get("sizeKB")
    try:
        return int(float(size_kb) * 1024) if size_kb else None
    except (TypeError, ValueError):
        return None


def _delete_candidates(model_path: Path) -> list[Path]:
    candidates = [model_path, metadata_path_for(model_path)]
    candidates.extend(model_path.with_suffix(extension) for extension in PREVIEW_EXTENSIONS)
    return list(dict.fromkeys(candidates))


def _add_static_route(app: web.Application, prefix: str, path: Path) -> None:
    if not path.exists():
        return
    for resource in app.router.resources():
        if getattr(resource, "canonical", None) == prefix:
            return
    app.router.add_static(prefix, path)


def _html_response(path: Path) -> web.FileResponse:
    response = web.FileResponse(path)
    response.headers["Cache-Control"] = "no-store"
    return response


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _api_key_source(settings: dict[str, Any]) -> str:
    if os.environ.get("CIVITAI_API_KEY") or os.environ.get("LORA_LITE_CIVITAI_API_KEY"):
        return "environment"
    if str(settings.get("civitai_api_key", "") or "").strip():
        return "settings"
    return ""


def _metadata_from_version(version: dict[str, Any], file_info: dict[str, Any], file_path: str | Path) -> dict[str, Any]:
    model = version.get("model") if isinstance(version.get("model"), dict) else {}
    hashes = file_info.get("hashes") if isinstance(file_info.get("hashes"), dict) else {}
    trained_words = version.get("trainedWords")
    images = version.get("images")
    model_id = model.get("id")
    model_version_id = version.get("id")
    model_page_url = f"https://civitai.com/models/{model_id}?modelVersionId={model_version_id}" if model_id and model_version_id else ""
    download_url = normalize_download_url(str(file_info.get("downloadUrl") or f"{CIVITAI_DOWNLOAD_PREFIX}{model_version_id}")) if model_version_id else ""

    return {
        "model_name": model.get("name") or version.get("name") or Path(file_path).stem,
        "file_name": Path(file_path).stem,
        "file_path": normalize_path(file_path),
        "base_model": version.get("baseModel", ""),
        "sha256": str(hashes.get("SHA256", "") or "").lower(),
        "trigger_words": trained_words if isinstance(trained_words, list) else [],
        "trained_words": trained_words if isinstance(trained_words, list) else [],
        "notes": "",
        "preview_url": "",
        "source_url": model_page_url,
        "download_url": download_url,
        "civitai": {
            "modelId": model_id,
            "modelVersionId": model_version_id,
            "modelPageUrl": model_page_url,
            "downloadUrl": download_url,
            "model": model,
            "version": version,
            "file": file_info,
            "images": images if isinstance(images, list) else [],
        },
    }
