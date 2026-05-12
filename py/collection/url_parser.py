from __future__ import annotations

import re
from urllib.parse import urlparse


def parse_civitai_image_id(value: str) -> str:
    text = value.strip()
    if not text:
        return ""

    if text.isdigit():
        return text

    parsed = urlparse(text)
    image_match = re.search(r"/images/(\d+)", parsed.path)
    if image_match:
        return image_match.group(1)

    return ""
