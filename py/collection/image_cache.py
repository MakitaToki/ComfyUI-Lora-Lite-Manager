from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ..downloader import Downloader
from .storage import COLLECTION_DIR


IMAGE_CACHE_DIR = COLLECTION_DIR / "images"


async def cache_image(url: str, artwork_id: str) -> str:
    if not url:
        return ""

    suffix = _suffix_from_url(url)
    target = IMAGE_CACHE_DIR / f"{_safe_name(artwork_id)}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        return str(target)

    await Downloader().download_file(url, target, use_auth=False)
    return str(target)


def _suffix_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return suffix
    return ".jpg"


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)

