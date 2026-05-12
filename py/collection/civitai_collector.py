from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from ..civitai import CIVITAI_API
from ..downloader import Downloader
from .image_cache import cache_image
from .normalizer import normalize_civitai_image
from .storage import upsert_artwork


class CivitaiArtworkCollector:
    def __init__(self, downloader: Downloader | None = None) -> None:
        self.downloader = downloader or Downloader()

    async def import_url(self, url: str, *, limit: int = 20, cache_images: bool = True) -> list[dict[str, Any]]:
        mode, value = parse_civitai_url(url)
        if not mode or not value:
            raise ValueError("请输入 Civitai 图片链接、模型链接，或 imageId/modelId")

        payload = await self._fetch_images(mode, value, limit=limit)
        items = payload.get("items") if isinstance(payload.get("items"), list) else []

        saved: list[dict[str, Any]] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            artwork = normalize_civitai_image(raw)
            if cache_images:
                try:
                    artwork["preview_path"] = await cache_image(artwork["image_url"], artwork["id"])
                except Exception:
                    artwork["preview_path"] = ""
            saved.append(upsert_artwork(artwork))
        return saved

    async def _fetch_images(self, mode: str, value: str, *, limit: int) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        params = {
            "limit": str(limit),
            "withMeta": "true",
        }
        if mode == "image":
            params["imageId"] = value
        elif mode == "model":
            params["modelId"] = value
            params["sort"] = "Most Reactions"
            params["period"] = "AllTime"
        elif mode == "model_version":
            params["modelVersionId"] = value
            params["sort"] = "Most Reactions"
            params["period"] = "AllTime"
        else:
            raise ValueError(f"不支持的 Civitai 导入类型：{mode}")

        url = f"{CIVITAI_API}/images?{urlencode(params)}"
        return await self.downloader.request_json(url, use_auth=True)


def parse_civitai_url(value: str) -> tuple[str, str]:
    text = value.strip()
    if not text:
        return "", ""

    if text.isdigit():
        return "image", text

    parsed = urlparse(text)
    query = parse_qs(parsed.query)

    if "modelVersionId" in query and query["modelVersionId"]:
        return "model_version", query["modelVersionId"][0]

    image_match = re.search(r"/images/(\d+)", parsed.path)
    if image_match:
        return "image", image_match.group(1)

    model_match = re.search(r"/models/(\d+)", parsed.path)
    if model_match:
        return "model", model_match.group(1)

    return "", ""
