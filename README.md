# LoRA Lite Manager

A minimal ComfyUI plugin focused only on LoRA management.

## Scope

- Scan LoRA folders from ComfyUI `folder_paths`.
- Browse and search local LoRA files in a lightweight `/lora-lite` page.
- Read and write `.metadata.json` sidecar files.
- Calculate SHA256 on demand.
- Query Civitai by SHA256.
- Download a Civitai model version into a LoRA folder.
- Use explicit HTTP/HTTPS proxy settings for API and file downloads.

It intentionally does not include recipes, checkpoints, embeddings, randomizers, virtual scrolling, batch tools, or a full standalone app.

## Install

Clone or link this repository into:

```text
ComfyUI/custom_nodes/lora_lite_manager
```

Restart ComfyUI.

Open:

```text
http://127.0.0.1:8188/lora-lite
```

The plugin also adds a small ComfyUI top-bar button that opens the same page.

For local development on Windows, use a junction instead of copying files:

```powershell
New-Item -ItemType Junction `
  -Path "D:\ComfyUI\custom_nodes\lora_lite_manager" `
  -Target "C:\path\to\lora_lite_manager"
```

## Optional Settings

Copy `settings.example.json` to `settings.json` and edit it.

```json
{
  "civitai_api_key": "your_key",
  "proxy": {
    "enabled": true,
    "type": "http",
    "host": "127.0.0.1",
    "port": "7890"
  }
}
```

You can also use environment variables:

- `CIVITAI_API_KEY`
- `LORA_LITE_CIVITAI_API_KEY`
- `LORA_LITE_PROXY`, for example `http://127.0.0.1:7890`

SOCKS proxies are intentionally rejected unless `aiohttp-socks` is installed and integrated later.

## API

- `GET /lora-lite`
- `GET /api/lora-lite/roots`
- `GET /api/lora-lite/loras`
- `POST /api/lora-lite/scan`
- `POST /api/lora-lite/hash`
- `GET /api/lora-lite/preview?path=...`
- `GET /api/lora-lite/civitai/by-hash/{sha256}`
- `POST /api/lora-lite/metadata`
- `POST /api/lora-lite/download`

Example download payload:

```json
{
  "model_version_id": 123456,
  "relative_dir": "SDXL/character"
}
```
