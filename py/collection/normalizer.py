from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def normalize_civitai_image(item: dict[str, Any]) -> dict[str, Any]:
    image_id = str(item.get("id") or "").strip()
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}

    positive = _first_text(meta, ("prompt", "Prompt", "positivePrompt", "Positive prompt"))
    negative = _first_text(meta, ("negativePrompt", "Negative prompt", "negative_prompt"))
    tags = _extract_tags(item, positive)
    model_refs = _extract_model_refs(item, meta)
    generation = _extract_generation(meta)

    return {
        "id": f"civitai_image_{image_id}",
        "source": "civitai",
        "asset_type": "ai_generation_reference",
        "source_id": image_id,
        "source_url": f"https://civitai.com/images/{image_id}" if image_id else "",
        "image_url": str(item.get("url") or ""),
        "preview_path": "",
        "width": _as_int(item.get("width")),
        "height": _as_int(item.get("height")),
        "nsfw": item.get("nsfw"),
        "nsfw_level": item.get("nsfwLevel"),
        "creator": _creator_name(item),
        "positive_prompt": positive,
        "negative_prompt": negative,
        "raw_tags": tags,
        "model_refs": model_refs,
        "stats": stats,
        "meta": {**meta, "generation": generation},
        "visual_structure": {},
        "design_language": {},
        "transfer": {
            "use_for_generation": ["prompt", "style", "composition", "lora_test"],
            "use_for_postprocess": [],
            "do_not_generate": [],
            "requires_design_stage": False,
        },
        "aigc_seed": generation,
        "retrieval": {
            "keywords_zh": [],
            "keywords_en": tags[:24],
            "embedding_text": positive,
        },
        "user_notes": "",
        "created_at": str(item.get("createdAt") or ""),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_tags(item: dict[str, Any], positive_prompt: str) -> list[str]:
    tags: list[str] = []

    for tag in item.get("tags") or []:
        if isinstance(tag, str):
            tags.append(tag)
        elif isinstance(tag, dict) and isinstance(tag.get("name"), str):
            tags.append(tag["name"])

    if positive_prompt:
        for part in positive_prompt.split(","):
            tag = part.strip()
            if tag and len(tag) <= 80:
                tags.append(tag)

    return _dedupe(tags)


def _extract_model_refs(item: dict[str, Any], meta: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []

    for key in ("resources", "Resources", "models", "Models"):
        resources = meta.get(key)
        if not isinstance(resources, list):
            continue
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            resource_type = resource.get("type") or resource.get("modelType") or resource.get("model_type") or ""
            refs.append(
                {
                    "name": resource.get("name") or resource.get("modelName") or "",
                    "type": str(resource_type).upper() if resource_type else "",
                    "version": resource.get("version") or resource.get("modelVersionName") or "",
                    "weight": resource.get("weight") or resource.get("strength"),
                    "model_version_id": resource.get("modelVersionId") or resource.get("model_version_id"),
                    "model_id": resource.get("modelId") or resource.get("model_id"),
                    "hash": resource.get("hash") or resource.get("sha256") or "",
                }
            )

    model = item.get("model") if isinstance(item.get("model"), dict) else {}
    if model:
        refs.append(
            {
                "name": model.get("name") or "",
                "type": model.get("type") or "",
                "model_id": model.get("id"),
            }
        )

    return [ref for ref in refs if any(ref.values())]


def _extract_generation(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "cfg_scale": _first_existing(meta, ("cfgScale", "CFG scale", "cfg_scale", "cfg")),
        "steps": _first_existing(meta, ("steps", "Steps")),
        "sampler": _first_existing(meta, ("sampler", "Sampler")),
        "seed": _first_existing(meta, ("seed", "Seed")),
        "clip_skip": _first_existing(meta, ("clipSkip", "Clip skip", "clip_skip")),
        "size": _first_existing(meta, ("Size", "size")),
        "model": _first_existing(meta, ("Model", "model", "modelName")),
        "scheduler": _first_existing(meta, ("scheduler", "Scheduler")),
    }


def _first_existing(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return ""


def _creator_name(item: dict[str, Any]) -> str:
    username = item.get("username")
    if isinstance(username, str) and username:
        return username
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    return str(user.get("username") or user.get("name") or "")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(value.strip().split())
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result
