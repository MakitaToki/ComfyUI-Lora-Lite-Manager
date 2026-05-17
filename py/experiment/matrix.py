from __future__ import annotations

import hashlib
import json
from typing import Any


DEFAULT_GENERATION = {
    "seed": -1,
    "steps": 22,
    "cfg": 6,
    "sampler": "euler_ancestral",
    "scheduler": "normal",
    "denoise": 1,
    "width": 1024,
    "height": 1536,
    "clip_skip": 2,
    "batch_size": 1,
}

DEFAULT_NEGATIVE = "bad quality, worst quality, sketch, bad hands, bad anatomy, watermark, signature"


def build_experiment_cases(
    items: list[dict[str, Any]],
    *,
    title_prefix: str = "lora_lite_exp",
    workflow_profile: str = "advanced_v34",
    checkpoint: str = "",
    loras: list[dict[str, Any]] | None = None,
    use_source_loras: bool = False,
    generation_defaults: dict[str, Any] | None = None,
    use_source_generation: bool = True,
) -> list[dict[str, Any]]:
    defaults = {**DEFAULT_GENERATION, **(generation_defaults or {})}
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        compiled = _compile_prompt(item)
        generation = _generation(item, defaults, use_source_generation=use_source_generation)
        case_id = _case_id(item, index)
        case_loras = _normalize_loras(loras or [])
        if use_source_loras and not case_loras:
            case_loras = _loras_from_model_refs(item.get("model_refs", []))

        case = {
            "case_id": case_id,
            "workflow_profile": workflow_profile,
            "source_seed_ids": [f"seed_{item.get('id', case_id)}"],
            "source_artwork_ids": [item.get("id", "")],
            "source": {
                "asset_type": item.get("asset_type", "ai_generation_reference"),
                "source": item.get("source", ""),
                "source_url": item.get("source_url", ""),
                "image_path": item.get("preview_path", ""),
            },
            "compile_status": compiled["status"],
            "compile_warnings": compiled["warnings"],
            "prompt": {
                "positive": compiled["positive"],
                "negative": compiled["negative"],
                "style_notes": _style_notes(item),
                "prompt_compile": compiled["prompt_compile"],
            },
            "models": {
                "checkpoint": checkpoint or _string(item.get("aigc_seed", {}).get("model")) or "",
                "loras": case_loras,
                "source_model_refs": item.get("model_refs", []),
            },
            "generation": generation,
            "output": {
                "filename_prefix": f"{title_prefix}_{index:04d}_{_safe_slug(_title(item))}",
            },
        }
        cases.append(case)
    return cases


def _compile_prompt(item: dict[str, Any]) -> dict[str, Any]:
    asset_type = item.get("asset_type") or "ai_generation_reference"
    positive = _string(item.get("positive_prompt")).strip()
    negative = _string(item.get("negative_prompt")).strip() or DEFAULT_NEGATIVE
    warnings: list[str] = []
    prompt_compile = {
        "strategy": "source_prompt" if positive else "visual_reference_draft",
        "sent_to_comfyui": ["positive", "negative"],
        "kept_as_notes": ["style_notes", "design_language", "transfer", "user_notes"],
    }

    if positive:
        return {
            "status": "ready",
            "positive": positive,
            "negative": negative,
            "warnings": warnings,
            "prompt_compile": prompt_compile,
        }

    prompt_compile.update(
        {
            "strategy": "visual_reference_requires_rewrite",
            "candidate_terms": _candidate_terms(item),
        }
    )
    warnings.append("Visual reference has no AI-ready positive prompt; runner will skip it by default.")
    return {
        "status": "draft",
        "positive": "",
        "negative": negative,
        "warnings": warnings,
        "prompt_compile": prompt_compile,
    }


def _candidate_terms(item: dict[str, Any]) -> dict[str, Any]:
    visual = item.get("visual_structure") if isinstance(item.get("visual_structure"), dict) else {}
    retrieval = item.get("retrieval") if isinstance(item.get("retrieval"), dict) else {}
    return {
        "subject": visual.get("subject", ""),
        "composition": visual.get("composition", ""),
        "lighting": visual.get("lighting", ""),
        "keywords_en": retrieval.get("keywords_en", []),
        "keywords_zh": retrieval.get("keywords_zh", []),
        "user_notes": item.get("user_notes", ""),
    }


def _generation(item: dict[str, Any], defaults: dict[str, Any], *, use_source_generation: bool = True) -> dict[str, Any]:
    if not use_source_generation:
        return dict(defaults)

    seed = item.get("aigc_seed") if isinstance(item.get("aigc_seed"), dict) else {}
    generation = {
        **defaults,
        "seed": _int(seed.get("seed"), defaults["seed"]),
        "steps": _int(seed.get("steps"), defaults["steps"]),
        "cfg": _float(seed.get("cfg_scale"), defaults["cfg"]),
        "sampler": _sampler(seed.get("sampler") or defaults["sampler"]),
        "scheduler": _scheduler(seed.get("scheduler") or seed.get("schedule_type") or defaults["scheduler"]),
        "width": _int(seed.get("width"), defaults["width"]),
        "height": _int(seed.get("height"), defaults["height"]),
        "clip_skip": _int(seed.get("clip_skip"), defaults["clip_skip"]),
    }
    size = seed.get("size")
    if isinstance(size, str) and "x" in size.lower():
        width, height = size.lower().split("x", 1)
        generation["width"] = _int(width, generation["width"])
        generation["height"] = _int(height, generation["height"])
    return generation


def _style_notes(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_type": item.get("asset_type", ""),
        "visual_structure": item.get("visual_structure", {}),
        "design_language": item.get("design_language", {}),
        "transfer": item.get("transfer", {}),
        "user_notes": item.get("user_notes", ""),
    }


def _normalize_loras(loras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in loras:
        name = _string(item.get("name") or item.get("lora_name")).strip()
        if not name:
            continue
        strength = _float(item.get("strength") or item.get("strength_model"), 0.7)
        clip_strength = _float(item.get("clipStrength") or item.get("strength_clip"), strength)
        result.append(
            {
                "name": name,
                "strength": round(strength, 3),
                "clipStrength": round(clip_strength, 3),
                "active": bool(item.get("active", True)),
            }
        )
    return result


def _loras_from_model_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    loras: list[dict[str, Any]] = []
    for ref in refs:
        if _string(ref.get("type")).upper() != "LORA":
            continue
        name = _string(ref.get("name")).strip()
        if not name:
            continue
        weight = _float(ref.get("weight"), 0.7)
        loras.append({"name": name, "strength": weight, "clipStrength": weight, "active": True})
    return loras


def _case_id(item: dict[str, Any], index: int) -> str:
    source = f"{item.get('id', '')}:{index}"
    return "case_" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:12]


def _title(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return _string(meta.get("title") or item.get("user_notes") or item.get("source_id") or item.get("id") or "seed")


def _safe_slug(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isascii() and char.isalnum():
            chars.append(char)
        elif char in {" ", "-", "_"}:
            chars.append("_")
    slug = "".join(chars).strip("_")
    return slug[:40] or "seed"


def _looks_prompt_safe(value: Any) -> bool:
    text = _string(value).strip()
    return bool(text) and text.isascii() and len(text) <= 80 and "http" not in text.lower()


def _sampler(value: Any) -> str:
    text = _string(value).strip().lower().replace(" ", "_")
    if text in {"", "undefined", "none", "null"}:
        return DEFAULT_GENERATION["sampler"]
    mapping = {
        "euler_a": "euler_ancestral",
        "euler_ancestral": "euler_ancestral",
        "euler": "euler",
        "dpm++_2m": "dpmpp_2m",
        "dpm++_2m_sde": "dpmpp_2m_sde",
    }
    return mapping.get(text, text or DEFAULT_GENERATION["sampler"])


def _scheduler(value: Any) -> str:
    text = _string(value).strip().lower().replace(" ", "_")
    if text in {"", "undefined", "none", "null"}:
        return DEFAULT_GENERATION["scheduler"]
    mapping = {"karras": "karras", "normal": "normal", "simple": "simple"}
    return mapping.get(text, text or DEFAULT_GENERATION["scheduler"])


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
