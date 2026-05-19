from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

from .downloader import Downloader


CIVITAI_API = "https://civitai.com/api/v1"
CIVITAI_DOWNLOAD_PREFIX = "https://civitai.com/api/download/models/"


def normalize_download_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname == "civitai.red" and parsed.path.startswith("/api/download/"):
        return urlunparse(parsed._replace(netloc="civitai.com"))
    return url


def select_model_file(version: dict[str, Any], file_params: dict[str, Any] | None = None) -> dict[str, Any]:
    files = version.get("files")
    if not isinstance(files, list):
        return {}

    params = file_params or {}
    candidates = [item for item in files if isinstance(item, dict)]

    for key, value in params.items():
        if value in (None, ""):
            continue
        candidates = [item for item in candidates if item.get(key) == value]

    primary = next((item for item in candidates if item.get("primary")), None)
    return primary or (candidates[0] if candidates else {})


class CivitaiClient:
    def __init__(self, downloader: Downloader | None = None) -> None:
        self.downloader = downloader or Downloader()

    async def get_model_version(self, model_version_id: int) -> dict[str, Any]:
        return await self.downloader.request_json(
            f"{CIVITAI_API}/model-versions/{model_version_id}",
            use_auth=True,
        )

    async def get_model(self, model_id: int) -> dict[str, Any]:
        return await self.downloader.request_json(
            f"{CIVITAI_API}/models/{model_id}",
            use_auth=True,
        )

    async def get_model_by_hash(self, sha256: str) -> dict[str, Any]:
        return await self.downloader.request_json(
            f"{CIVITAI_API}/model-versions/by-hash/{sha256}",
            use_auth=True,
        )
