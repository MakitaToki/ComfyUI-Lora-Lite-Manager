# LoRA Lite Manager

A minimal ComfyUI plugin focused only on LoRA management.

## Scope

- Scan LoRA folders from ComfyUI `folder_paths`.
- Provide a small `LoRA Lite Loader` ComfyUI node for API-driven experiment workflows.
- Browse and search local LoRA files in a lightweight `/lora-lite` page.
- Read and write `.metadata.json` sidecar files.
- Calculate SHA256 on demand.
- Query Civitai by SHA256.
- Download a Civitai model version into a LoRA folder.
- Use explicit HTTP/HTTPS proxy settings for API and file downloads.
- Build a lightweight Civitai artwork collection at `/collection-lite` for prompt/tag research.
- Add manual visual references from image URLs or local image paths, with separate asset types for AI generation, photography, and graphic design references.
- Export first-pass experiment cases from collection items, and run ready cases through an `Advanced_V34` ComfyUI API workflow.

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
- `GET /collection-lite`
- `POST /api/lora-lite/collection/import`
- `POST /api/lora-lite/collection/manual`
- `GET /api/lora-lite/collection/items`
- `GET /api/lora-lite/collection/items/{artwork_id}`
- `PATCH /api/lora-lite/collection/items/{artwork_id}`
- `POST /api/lora-lite/collection/export-seeds`
- `POST /api/lora-lite/experiments/cases`
- `POST /api/lora-lite/experiments/preview`
- `POST /api/lora-lite/experiments/runs`
- `GET /api/lora-lite/experiments/runs`
- `GET /api/lora-lite/experiments/runs/{run_id}`
- `POST /api/lora-lite/experiments/runs/{run_id}/refresh`

Example download payload:

```json
{
  "model_version_id": 123456,
  "relative_dir": "SDXL/character"
}
```

## Experiment Matrix

The first experiment matrix format is intentionally conservative:

- Civitai images or any item with an AI-ready `positive_prompt` become `ready` cases.
- Pinterest, Xiaohongshu, and local visual references without an AI-ready prompt become `draft` cases.
- Draft cases keep `visual_structure`, `design_language`, transfer rules, and notes as `style_notes`; those notes are not sent to ComfyUI.
- The runner skips draft cases unless `--include-draft` is passed.
- The default runner workflow is `workflows/lora_lite_base_api.json`, a minimal API workflow built around `LoraLiteLoader`.
- Passing an `Advanced_V34` API workflow is still supported for comparison; node `56` is patched to `LoraLiteLoader` by default.
- Recipe Lite's experiment workspace expands preview cases as `prompt variant x LoRA combo x strength x seed`.
- LoRA combos include baseline, each single LoRA, and every two-LoRA pair. Pair members share the same strength value for each sweep step.
- Experiment runs are saved locally under `data/experiments` and can be refreshed from ComfyUI history.

Export cases from the local collection:

```powershell
python tools\run_advanced_v34_experiment.py --from-collection --limit 3
```

Patch and save Advanced_V34 workflow JSON without submitting:

```powershell
python tools\run_advanced_v34_experiment.py `
  --from-collection `
  --limit 3 `
  --output-dir data\experiments\patched
```

Submit ready cases to ComfyUI with the minimal base workflow:

```powershell
python tools\run_advanced_v34_experiment.py `
  --from-collection `
  --limit 1 `
  --comfyui-url http://127.0.0.1:8188 `
  --submit `
  --wait
```

Run against an Advanced_V34 API workflow instead:

```powershell
python tools\run_advanced_v34_experiment.py `
  --from-collection `
  --limit 1 `
  --workflow "C:\Users\Administrator\Downloads\Advanced_V34.json" `
  --submit
```

Keep the original LoRA Manager node for comparison:

```powershell
python tools\run_advanced_v34_experiment.py `
  --from-collection `
  --lora-node original `
  --submit
```

Override LoRAs explicitly:

```powershell
python tools\run_advanced_v34_experiment.py `
  --from-collection `
  --lora "BlueArcStyle.safetensors:0.7" `
  --submit
```
