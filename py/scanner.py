from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .config import get_lora_roots
from .metadata import (
    SUPPORTED_MODEL_EXTENSIONS,
    load_metadata,
    normalize_path,
    preview_path_for,
)


def _model_to_record(model_path: Path, root: Path) -> dict[str, Any]:
    stat = model_path.stat()
    metadata = load_metadata(model_path)
    relative_path = model_path.relative_to(root)
    trigger_words = metadata.get("trigger_words")
    if not isinstance(trigger_words, list):
        trigger_words = metadata.get("trained_words", [])

    return {
        "name": metadata.get("model_name") or model_path.stem,
        "file_name": model_path.name,
        "file_path": normalize_path(model_path),
        "relative_path": normalize_path(relative_path),
        "root": normalize_path(root),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "sha256": metadata.get("sha256", ""),
        "preview_path": metadata.get("preview_url") or preview_path_for(model_path),
        "tags": metadata.get("tags", []),
        "trigger_words": trigger_words if isinstance(trigger_words, list) else [],
        "trained_words": metadata.get("trained_words", []),
        "notes": metadata.get("notes", ""),
        "base_model": metadata.get("base_model", ""),
        "civitai": metadata.get("civitai", {}),
        "metadata": metadata,
    }


def scan_loras() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for root_value in get_lora_roots():
        root = Path(root_value)
        if not root.exists():
            continue

        for directory, _, filenames in os.walk(root):
            for filename in filenames:
                model_path = Path(directory) / filename
                if model_path.suffix.lower() not in SUPPORTED_MODEL_EXTENSIONS:
                    continue
                records.append(_model_to_record(model_path, root))

    records.sort(key=lambda item: item["relative_path"].lower())
    return records


def find_lora_by_path(file_path: str) -> dict[str, Any] | None:
    normalized = normalize_path(file_path)
    for record in scan_loras():
        if record["file_path"] == normalized:
            return record
    return None
