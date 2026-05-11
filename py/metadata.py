from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SUPPORTED_MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth"}
PREVIEW_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}


def normalize_path(path: str | Path) -> str:
    return str(Path(path)).replace(os.sep, "/")


def metadata_path_for(model_path: str | Path) -> Path:
    model = Path(model_path)
    return model.with_suffix(".metadata.json")


def preview_path_for(model_path: str | Path) -> str:
    model = Path(model_path)
    for extension in PREVIEW_EXTENSIONS:
        candidate = model.with_suffix(extension)
        if candidate.exists():
            return normalize_path(candidate)
    return ""


def load_metadata(model_path: str | Path) -> dict[str, Any]:
    sidecar = metadata_path_for(model_path)
    if not sidecar.exists():
        return {}

    try:
        with sidecar.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {"metadata_error": f"Failed to parse {normalize_path(sidecar)}"}


def save_metadata(model_path: str | Path, metadata: dict[str, Any]) -> None:
    sidecar = metadata_path_for(model_path)
    sidecar.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(metadata)
    payload["file_path"] = normalize_path(model_path)

    temp_path = sidecar.with_suffix(sidecar.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, sidecar)


def _calculate_sha256_sync(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def calculate_sha256(path: str | Path) -> str:
    return await asyncio.to_thread(_calculate_sha256_sync, path)
