from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = PLUGIN_ROOT / "settings.json"


@dataclass(frozen=True)
class ProxyConfig:
    enabled: bool = False
    proxy_type: str = "http"
    host: str = ""
    port: str = ""
    username: str = ""
    password: str = ""

    @property
    def url(self) -> str | None:
        if not self.enabled:
            return None

        env_proxy = os.environ.get("LORA_LITE_PROXY")
        if env_proxy:
            return env_proxy

        if not self.host or not self.port:
            return None

        auth = ""
        if self.username and self.password:
            auth = f"{self.username}:{self.password}@"
        return f"{self.proxy_type}://{auth}{self.host}:{self.port}"


@dataclass(frozen=True)
class PluginConfig:
    civitai_api_key: str = ""
    lora_roots: tuple[str, ...] = ()
    default_lora_root: str = ""
    proxy: ProxyConfig = ProxyConfig()
    download_chunk_size: int = 1024 * 1024
    max_retries: int = 3


def _read_settings_file() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}

    with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def load_config() -> PluginConfig:
    payload = _read_settings_file()
    proxy_payload = payload.get("proxy") if isinstance(payload.get("proxy"), dict) else {}

    api_key = (
        os.environ.get("CIVITAI_API_KEY")
        or os.environ.get("LORA_LITE_CIVITAI_API_KEY")
        or str(payload.get("civitai_api_key", "") or "")
    )

    lora_roots_raw = payload.get("lora_roots", [])
    lora_roots = tuple(str(path) for path in lora_roots_raw if isinstance(path, str))

    return PluginConfig(
        civitai_api_key=api_key.strip(),
        lora_roots=lora_roots,
        default_lora_root=str(payload.get("default_lora_root", "") or "").strip(),
        proxy=ProxyConfig(
            enabled=bool(proxy_payload.get("enabled", False) or os.environ.get("LORA_LITE_PROXY")),
            proxy_type=str(proxy_payload.get("type", "http") or "http").lower(),
            host=str(proxy_payload.get("host", "") or "").strip(),
            port=str(proxy_payload.get("port", "") or "").strip(),
            username=str(proxy_payload.get("username", "") or "").strip(),
            password=str(proxy_payload.get("password", "") or "").strip(),
        ),
        download_chunk_size=int(payload.get("download_chunk_size", 1024 * 1024) or 1024 * 1024),
        max_retries=max(0, int(payload.get("max_retries", 3) or 3)),
    )


def get_lora_roots() -> list[str]:
    config = load_config()
    roots = list(config.lora_roots)

    if not roots:
        try:
            import folder_paths  # type: ignore

            roots = list(folder_paths.get_folder_paths("loras"))
        except Exception:
            roots = []

    return [str(Path(path)) for path in roots if path and Path(path).exists()]


def get_default_lora_root() -> str:
    config = load_config()
    if config.default_lora_root and Path(config.default_lora_root).exists():
        return config.default_lora_root

    roots = get_lora_roots()
    return roots[0] if roots else ""
