from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..metadata import load_metadata

logger = logging.getLogger(__name__)


class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False


class FlexibleOptionalInputType(dict):
    def __init__(self, input_type: Any):
        self.input_type = input_type

    def __getitem__(self, key: str) -> tuple[Any]:
        return (self.input_type,)

    def __contains__(self, key: object) -> bool:
        return True


ANY = AnyType("*")


class LoraLiteLoader:
    CATEGORY = "LoRA Lite/loaders"
    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING")
    RETURN_NAMES = ("MODEL", "CLIP", "trigger_words", "loaded_loras")
    FUNCTION = "load_loras"

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "model": ("MODEL",),
                "text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "tooltip": "Optional LoRA syntax: <lora:name:strength> or <lora:name:model_strength:clip_strength>",
                    },
                ),
            },
            "optional": FlexibleOptionalInputType(ANY),
        }

    def load_loras(self, model: Any, text: str = "", **kwargs: Any) -> tuple[Any, Any, str, str]:
        clip = kwargs.get("clip")
        entries = _collect_entries(text, kwargs.get("loras"))
        loaded: list[dict[str, Any]] = []
        trigger_words: list[str] = []

        for entry in entries:
            if not entry.get("active", True):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue

            strength = _float(entry.get("strength"), 0.7)
            clip_strength = _float(entry.get("clipStrength"), strength)

            try:
                model, clip, metadata = _load_lora(model, clip, name, strength, clip_strength)
            except Exception as exc:
                logger.warning("Skipping LoRA %s: %s", name, exc)
                continue

            loaded.append({"name": name, "strength": strength, "clipStrength": clip_strength})
            trigger_words.extend(_metadata_trigger_words(metadata))

        loaded_loras = " ".join(_format_lora(item) for item in loaded)
        return model, clip, ",, ".join(_dedupe(trigger_words)), loaded_loras


def _collect_entries(text: str, raw_loras: Any) -> list[dict[str, Any]]:
    entries = _entries_from_raw(raw_loras)
    entries.extend(_entries_from_text(text))
    return entries


def _entries_from_raw(raw_loras: Any) -> list[dict[str, Any]]:
    if isinstance(raw_loras, dict) and "__value__" in raw_loras:
        raw_loras = raw_loras["__value__"]
    if isinstance(raw_loras, str):
        try:
            raw_loras = json.loads(raw_loras)
        except json.JSONDecodeError:
            return _entries_from_text(raw_loras)
    if not isinstance(raw_loras, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in raw_loras:
        if isinstance(item, dict):
            entries.append(
                {
                    "name": item.get("name") or item.get("lora_name"),
                    "strength": item.get("strength") or item.get("strength_model"),
                    "clipStrength": item.get("clipStrength") or item.get("strength_clip"),
                    "active": item.get("active", True),
                }
            )
    return entries


def _entries_from_text(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    pattern = r"<lora:([^:>]+):([^:>]+)(?::([^:>]+))?>"
    for name, strength, clip_strength in re.findall(pattern, text or "", re.IGNORECASE):
        model_strength = _float(strength, 0.7)
        entries.append(
            {
                "name": name.strip(),
                "strength": model_strength,
                "clipStrength": _float(clip_strength, model_strength) if clip_strength else model_strength,
                "active": True,
            }
        )
    return entries


def _load_lora(model: Any, clip: Any, name: str, strength: float, clip_strength: float) -> tuple[Any, Any, dict[str, Any]]:
    import comfy.sd  # type: ignore
    import comfy.utils  # type: ignore
    import folder_paths  # type: ignore

    lora_path = folder_paths.get_full_path("loras", name)
    if not lora_path:
        lora_path = folder_paths.get_full_path("loras", _with_safetensors(name))
    if not lora_path:
        raise FileNotFoundError(f"LoRA not found: {name}")

    lora = comfy.utils.load_torch_file(lora_path, safe_load=True)
    next_model, next_clip = comfy.sd.load_lora_for_models(model, clip, lora, strength, clip_strength)
    return next_model, next_clip, load_metadata(lora_path)


def _metadata_trigger_words(metadata: dict[str, Any]) -> list[str]:
    for key in ("trigger_words", "trained_words"):
        value = metadata.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    return []


def _format_lora(item: dict[str, Any]) -> str:
    name = item["name"]
    strength = item["strength"]
    clip_strength = item["clipStrength"]
    if abs(float(strength) - float(clip_strength)) < 0.001:
        return f"<lora:{name}:{strength}>"
    return f"<lora:{name}:{strength}:{clip_strength}>"


def _with_safetensors(name: str) -> str:
    return name if Path(name).suffix else f"{name}.safetensors"


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


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


NODE_CLASS_MAPPINGS = {
    "LoraLiteLoader": LoraLiteLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoraLiteLoader": "LoRA Lite Loader",
}
