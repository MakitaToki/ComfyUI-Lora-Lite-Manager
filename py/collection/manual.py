from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .image_cache import cache_image, cache_local_image
from .storage import upsert_artwork


ASSET_TYPES = {
    "ai_generation_reference",
    "photo_reference",
    "graphic_design_reference",
}


async def add_manual_reference(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    source_url = str(source.get("source_url") or payload.get("source_url") or "").strip()
    image_url = str(source.get("image_url") or payload.get("image_url") or "").strip()
    local_image_path = str(source.get("local_image_path") or payload.get("local_image_path") or "").strip()
    platform = str(source.get("platform") or payload.get("platform") or "web").strip() or "web"
    asset_type = str(payload.get("asset_type") or "photo_reference").strip()

    if asset_type not in ASSET_TYPES:
        raise ValueError(f"Unsupported asset_type: {asset_type}")
    if not image_url and not local_image_path:
        raise ValueError("image_url or local_image_path is required")

    asset_id = _asset_id(platform, source_url or image_url or local_image_path)
    preview_path = ""
    if local_image_path:
        preview_path = cache_local_image(local_image_path, asset_id)
    elif image_url:
        try:
            preview_path = await cache_image(image_url, asset_id)
        except Exception:
            preview_path = ""

    tags = _split_lines(payload.get("tags")) + _split_lines(payload.get("keywords_zh"))
    now = datetime.now(timezone.utc).isoformat()

    artwork = {
        "id": asset_id,
        "source": platform,
        "asset_type": asset_type,
        "source_id": _short_hash(source_url or image_url or local_image_path),
        "source_url": source_url,
        "image_url": image_url,
        "preview_path": preview_path,
        "width": None,
        "height": None,
        "nsfw": None,
        "nsfw_level": None,
        "creator": str(payload.get("creator") or ""),
        "positive_prompt": str(payload.get("positive_prompt") or ""),
        "negative_prompt": str(payload.get("negative_prompt") or ""),
        "raw_tags": _dedupe(tags),
        "model_refs": [],
        "stats": {},
        "meta": {"local_image_path": local_image_path},
        "visual_structure": _dict(payload.get("visual_structure")),
        "design_language": _dict(payload.get("design_language")),
        "transfer": _default_transfer(asset_type, _dict(payload.get("transfer"))),
        "aigc_seed": _dict(payload.get("aigc_seed")),
        "retrieval": _retrieval(payload),
        "user_notes": str(payload.get("user_notes") or ""),
        "created_at": now,
        "collected_at": now,
    }
    return upsert_artwork(artwork)


def _asset_id(platform: str, value: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    safe_platform = "".join(char if char.isalnum() else "_" for char in platform.lower()).strip("_") or "web"
    return f"{today}_{safe_platform}_{_short_hash(value)[:10]}"


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _retrieval(payload: dict[str, Any]) -> dict[str, Any]:
    retrieval = _dict(payload.get("retrieval"))
    return {
        "keywords_zh": _split_lines(payload.get("keywords_zh")) or retrieval.get("keywords_zh", []),
        "keywords_en": _split_lines(payload.get("keywords_en")) or retrieval.get("keywords_en", []),
        "embedding_text": str(payload.get("embedding_text") or retrieval.get("embedding_text") or ""),
    }


def _default_transfer(asset_type: str, transfer: dict[str, Any]) -> dict[str, Any]:
    if transfer:
        return transfer
    if asset_type == "graphic_design_reference":
        return {
            "use_for_generation": ["subject", "composition", "color", "mood"],
            "use_for_postprocess": ["typography", "layout", "filter"],
            "do_not_generate": ["exact text", "logo", "final typography"],
            "requires_design_stage": True,
        }
    if asset_type == "photo_reference":
        return {
            "use_for_generation": ["lighting", "composition", "camera_feel", "mood", "material"],
            "use_for_postprocess": ["crop", "color_grade"],
            "do_not_generate": ["exact person", "brand logo"],
            "requires_design_stage": False,
        }
    return {
        "use_for_generation": ["prompt", "style", "composition"],
        "use_for_postprocess": [],
        "do_not_generate": [],
        "requires_design_stage": False,
    }


def _split_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str):
        return []
    return [part.strip() for chunk in value.splitlines() for part in chunk.split(",") if part.strip()]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
