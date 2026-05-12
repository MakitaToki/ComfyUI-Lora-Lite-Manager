from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..civitai import CIVITAI_API
from ..downloader import Downloader
from .image_cache import cache_image
from .normalizer import normalize_civitai_image
from .storage import upsert_artwork
from .url_parser import parse_civitai_image_id


class CivitaiArtworkCollector:
    def __init__(self, downloader: Downloader | None = None) -> None:
        self.downloader = downloader or Downloader()

    async def import_url(self, url: str, *, cache_images: bool = True) -> list[dict[str, Any]]:
        image_id = parse_civitai_image_id(url)
        if not image_id:
            raise ValueError("请输入 Civitai 图片链接，例如 https://civitai.com/images/123456")

        payload = await self._fetch_image(image_id)
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

    async def _fetch_image(self, image_id: str) -> dict[str, Any]:
        params = {
            "limit": "1",
            "withMeta": "true",
            "imageId": image_id,
        }
        url = f"{CIVITAI_API}/images?{urlencode(params)}"
        return await self.downloader.request_json(url, use_auth=True)
