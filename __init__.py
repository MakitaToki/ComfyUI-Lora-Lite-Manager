from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from .py.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
except Exception as exc:  # pragma: no cover - ComfyUI import-time guard
    logger.exception("Failed to register LoRA Lite Manager nodes: %s", exc)
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./web"

try:
    from .py.routes import register_routes

    register_routes()
except Exception as exc:  # pragma: no cover - ComfyUI import-time guard
    logger.exception("Failed to register LoRA Lite Manager routes: %s", exc)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
