from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp

from .config import PluginConfig, load_config

logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    pass


class Downloader:
    def __init__(self, config: PluginConfig | None = None) -> None:
        self.config = config or load_config()

    async def request_json(
        self,
        url: str,
        *,
        use_auth: bool = False,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = self._headers(use_auth=use_auth)
        if headers:
            request_headers.update(headers)

        async with self._client_session() as session:
            async with session.get(
                url,
                headers=request_headers,
                proxy=self._aiohttp_proxy_url(),
            ) as response:
                if response.status == 401:
                    raise DownloadError("Unauthorized: missing or invalid Civitai API key")
                if response.status == 403:
                    raise DownloadError("Forbidden: Civitai denied access to this resource")
                if response.status == 404:
                    raise DownloadError("Not found")
                if response.status >= 400:
                    text = await response.text()
                    raise DownloadError(f"Request failed with status {response.status}: {text[:300]}")
                payload = await response.json()
                return payload if isinstance(payload, dict) else {"data": payload}

    async def download_file(
        self,
        url: str,
        save_path: str | Path,
        *,
        use_auth: bool = False,
        expected_size: int | None = None,
    ) -> str:
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        part_path = Path(str(target) + ".part")
        if expected_size and part_path.exists() and part_path.stat().st_size > expected_size:
            part_path.unlink()

        last_error = ""
        for attempt in range(self.config.max_retries + 1):
            try:
                await self._download_once(
                    url,
                    target,
                    part_path,
                    use_auth=use_auth,
                    expected_size=expected_size,
                )
                if expected_size and part_path.stat().st_size > expected_size:
                    raise DownloadError(
                        f"Downloaded file is larger than expected ({part_path.stat().st_size} > {expected_size})"
                    )
                os.replace(part_path, target)
                return str(target)
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Download attempt %s/%s failed for %s: %s",
                    attempt + 1,
                    self.config.max_retries + 1,
                    url,
                    exc,
                )
                if attempt < self.config.max_retries:
                    await asyncio.sleep(2**attempt)

        raise DownloadError(f"Download failed after {self.config.max_retries + 1} attempts: {last_error}")

    async def _download_once(
        self,
        url: str,
        target: Path,
        part_path: Path,
        *,
        use_auth: bool,
        expected_size: int | None,
    ) -> None:
        resume_offset = part_path.stat().st_size if part_path.exists() else 0
        if expected_size and resume_offset >= expected_size:
            part_path.unlink()
            resume_offset = 0

        headers = self._headers(use_auth=use_auth)
        headers["Accept-Encoding"] = "identity"
        if resume_offset:
            headers["Range"] = f"bytes={resume_offset}-"

        mode = "ab" if resume_offset else "wb"
        async with self._client_session() as session:
            async with session.get(
                url,
                headers=headers,
                allow_redirects=True,
                proxy=self._aiohttp_proxy_url(),
            ) as response:
                if response.status == 200 and resume_offset:
                    resume_offset = 0
                    mode = "wb"
                elif response.status == 206:
                    pass
                elif response.status == 401:
                    raise DownloadError("Unauthorized: missing or invalid Civitai API key")
                elif response.status == 403:
                    raise DownloadError("Forbidden: Civitai denied access to this file")
                elif response.status == 404:
                    raise DownloadError("File not found")
                elif response.status >= 400:
                    raise DownloadError(f"Download failed with status {response.status}")

                with part_path.open(mode) as handle:
                    async for chunk in response.content.iter_chunked(self.config.download_chunk_size):
                        if chunk:
                            handle.write(chunk)

        if not part_path.exists() or part_path.stat().st_size <= 0:
            raise DownloadError("Downloaded file is empty")
        if expected_size and part_path.stat().st_size < expected_size:
            raise DownloadError(
                f"Downloaded file is incomplete ({part_path.stat().st_size} < {expected_size})"
            )

    def _headers(self, *, use_auth: bool) -> dict[str, str]:
        headers = {
            "User-Agent": "ComfyUI-LoRA-Lite-Manager/0.1",
            "Accept": "application/json, */*",
        }
        if use_auth and self.config.civitai_api_key:
            headers["Authorization"] = f"Bearer {self.config.civitai_api_key}"
        return headers

    def _aiohttp_proxy_url(self) -> str | None:
        proxy_url = self.config.proxy.url
        if not proxy_url:
            return None

        proxy_type = proxy_url.split(":", 1)[0].lower()
        if proxy_type in {"socks4", "socks5"}:
            raise DownloadError(
                "SOCKS proxy requires aiohttp-socks. Use HTTP proxy or install aiohttp-socks."
            )
        return proxy_url

    def _client_session(self) -> aiohttp.ClientSession:
        timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=45)
        return aiohttp.ClientSession(timeout=timeout, trust_env=self.config.proxy.url is None)
