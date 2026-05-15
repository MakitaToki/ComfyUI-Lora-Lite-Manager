from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW = REPO_ROOT / "workflows" / "lora_lite_base_api.json"
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"


BASE_BINDINGS = {
    "positive_prompt": ("4", "text"),
    "negative_prompt": ("5", "text"),
    "lora_text": ("3", "text"),
    "lora_widget": ("3", "loras"),
    "steps": ("7", "steps"),
    "cfg": ("7", "cfg"),
    "sampler": ("7", "sampler_name"),
    "scheduler": ("7", "scheduler"),
    "denoise": ("7", "denoise"),
    "width": ("6", "width"),
    "height": ("6", "height"),
    "batch_size": ("6", "batch_size"),
    "checkpoint": ("1", "ckpt_name"),
    "seed": ("7", "seed"),
    "clip_skip": ("2", "stop_at_clip_layer"),
    "save_filename": ("9", "filename_prefix"),
}


ADVANCED_V34_BINDINGS = {
    "positive_prompt": ("55", "wildcard_text"),
    "positive_populated": ("55", "populated_text"),
    "negative_prompt": ("57", "wildcard_text"),
    "negative_populated": ("57", "populated_text"),
    "lora_text": ("56", "text"),
    "lora_widget": ("56", "loras"),
    "steps": ("58", "steps"),
    "cfg": ("58", "cfg"),
    "sampler": ("58", "sampler"),
    "scheduler": ("58", "scheduler"),
    "denoise": ("58", "denoise"),
    "width": ("69", "value"),
    "height": ("71", "value"),
    "batch_size": ("79", "value"),
    "checkpoint": ("101", "ckpt_name"),
    "seed": ("105", "seed"),
    "clip_skip": ("82", "stop_at_clip_layer"),
    "save_filename": ("122", "filename"),
    "save_path": ("122", "path"),
    "save_clip_skip": ("122", "clip_skip"),
}


def main() -> int:
    args = parse_args()
    workflow = read_json(args.workflow)
    cases_payload = load_cases(args)
    cases = cases_payload.get("cases", cases_payload if isinstance(cases_payload, list) else [])
    if not isinstance(cases, list):
        raise SystemExit("Cases payload must be a list or an object with a cases list.")

    ready_cases = [case for case in cases if args.include_draft or case.get("compile_status") == "ready"]
    if args.limit:
        ready_cases = ready_cases[: args.limit]

    if not ready_cases:
        print("No runnable cases. Visual references without compiled prompts are draft by default.")
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    submitted = []
    for case in ready_cases:
        patched = patch_workflow(workflow, case, save_path=args.save_path, lora_node=args.lora_node)
        if output_dir:
            path = output_dir / f"{case['case_id']}.json"
            path.write_text(json.dumps(patched, ensure_ascii=False, indent=2), encoding="utf-8")

        if args.submit:
            prompt_id = submit_prompt(args.comfyui_url, patched)
            submitted.append({"case_id": case["case_id"], "prompt_id": prompt_id})
            print(f"submitted {case['case_id']} -> {prompt_id}")
            if args.wait:
                wait_for_history(args.comfyui_url, prompt_id)
                print(f"completed {case['case_id']} -> {prompt_id}")
        else:
            positive = case.get("prompt", {}).get("positive", "")
            print(f"dry-run {case['case_id']}: {positive[:120]}")

    if submitted:
        print(json.dumps({"submitted": submitted}, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LoRA Lite experiment cases through a ComfyUI API workflow.")
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW, help="ComfyUI API workflow JSON path.")
    parser.add_argument("--cases", type=Path, help="Experiment cases JSON exported from LoRA Lite Manager.")
    parser.add_argument("--from-collection", action="store_true", help="Build cases from the local collection SQLite database.")
    parser.add_argument("--query", default="", help="Collection search query when using --from-collection.")
    parser.add_argument("--sort", default="popular", help="Collection sort when using --from-collection.")
    parser.add_argument("--collection-limit", type=int, default=20, help="Max collection items to compile.")
    parser.add_argument("--title-prefix", default="lora_lite_exp", help="Output filename prefix.")
    parser.add_argument("--checkpoint", default="", help="Override checkpoint name.")
    parser.add_argument("--lora", action="append", default=[], help="LoRA override: name[:strength[:clipStrength]]. Can be repeated.")
    parser.add_argument("--use-source-loras", action="store_true", help="Use LoRA refs parsed from Civitai metadata when no --lora is set.")
    parser.add_argument("--include-draft", action="store_true", help="Run draft visual-reference cases too.")
    parser.add_argument("--limit", type=int, default=0, help="Max runnable cases to process.")
    parser.add_argument("--output-dir", default="", help="Optional directory to save patched workflow JSON files.")
    parser.add_argument("--save-path", default="", help="Optional Image Saver output path inside ComfyUI.")
    parser.add_argument(
        "--lora-node",
        choices=("lite", "original"),
        default="lite",
        help="Patch Advanced_V34 node 56 to LoRA Lite Loader, or keep the original LoraManager node.",
    )
    parser.add_argument("--comfyui-url", default=DEFAULT_COMFYUI_URL, help="ComfyUI server URL.")
    parser.add_argument("--submit", action="store_true", help="Actually POST cases to ComfyUI /prompt. Omit for dry-run.")
    parser.add_argument("--wait", action="store_true", help="Poll /history until each submitted prompt completes.")
    return parser.parse_args()


def load_cases(args: argparse.Namespace) -> Any:
    if args.cases:
        return read_json(args.cases)
    if args.from_collection:
        sys.path.insert(0, str(REPO_ROOT))
        from py.collection.storage import search_artworks
        from py.experiment.matrix import build_experiment_cases

        result = search_artworks(query=args.query, sort=args.sort, limit=args.collection_limit)
        cases = build_experiment_cases(
            result["items"],
            title_prefix=args.title_prefix,
            checkpoint=args.checkpoint,
            loras=[parse_lora_spec(value) for value in args.lora],
            use_source_loras=args.use_source_loras,
        )
        return {"format": "lora_lite_experiment_cases.v1", "cases": cases}
    raise SystemExit("Use --cases FILE or --from-collection.")


def patch_workflow(
    base_workflow: dict[str, Any],
    case: dict[str, Any],
    *,
    save_path: str = "",
    lora_node: str = "lite",
) -> dict[str, Any]:
    workflow = json.loads(json.dumps(base_workflow))
    bindings = detect_bindings(workflow)
    prompt = case.get("prompt", {})
    models = case.get("models", {})
    generation = case.get("generation", {})
    output = case.get("output", {})
    loras = [lora for lora in models.get("loras", []) if lora.get("active", True)]

    if lora_node == "lite" and bindings is ADVANCED_V34_BINDINGS:
        configure_lora_lite_node(workflow)

    set_input(workflow, bindings, "positive_prompt", prompt.get("positive", ""))
    set_input(workflow, bindings, "negative_prompt", prompt.get("negative", ""))
    set_optional_input(workflow, bindings, "positive_populated", prompt.get("positive", ""))
    set_optional_input(workflow, bindings, "negative_populated", prompt.get("negative", ""))
    set_input(workflow, bindings, "lora_text", lora_syntax(loras))
    set_input(workflow, bindings, "lora_widget", {"__value__": loras})
    set_input(workflow, bindings, "steps", generation.get("steps", 28))
    set_input(workflow, bindings, "cfg", generation.get("cfg", 6))
    set_input(workflow, bindings, "sampler", generation.get("sampler", "euler_ancestral"))
    set_input(workflow, bindings, "scheduler", generation.get("scheduler", "normal"))
    set_input(workflow, bindings, "denoise", generation.get("denoise", 1))
    set_input(workflow, bindings, "width", generation.get("width", 1024))
    set_input(workflow, bindings, "height", generation.get("height", 1536))
    set_input(workflow, bindings, "batch_size", generation.get("batch_size", 1))
    if models.get("checkpoint"):
        set_input(workflow, bindings, "checkpoint", models["checkpoint"])
    set_input(workflow, bindings, "seed", generation.get("seed", -1))
    clip_skip = int(generation.get("clip_skip", 2) or 2)
    set_input(workflow, bindings, "clip_skip", -abs(clip_skip))
    set_optional_input(workflow, bindings, "save_clip_skip", clip_skip)
    set_input(workflow, bindings, "save_filename", output.get("filename_prefix") or case.get("case_id", "lora_lite_exp"))
    if save_path:
        set_optional_input(workflow, bindings, "save_path", save_path)
    return workflow


def patch_advanced_v34_workflow(
    base_workflow: dict[str, Any],
    case: dict[str, Any],
    *,
    save_path: str = "",
    lora_node: str = "lite",
) -> dict[str, Any]:
    return patch_workflow(base_workflow, case, save_path=save_path, lora_node=lora_node)


def detect_bindings(workflow: dict[str, Any]) -> dict[str, tuple[str, str]]:
    if workflow.get("3", {}).get("class_type") == "LoraLiteLoader":
        return BASE_BINDINGS
    return ADVANCED_V34_BINDINGS


def configure_lora_lite_node(workflow: dict[str, Any]) -> None:
    node = workflow.get("56")
    if not isinstance(node, dict):
        raise KeyError("Advanced_V34 LoRA node 56 not found.")
    node["class_type"] = "LoraLiteLoader"
    node["_meta"] = {"title": "LoRA Lite Loader"}


def set_input(workflow: dict[str, Any], bindings: dict[str, tuple[str, str]], binding_name: str, value: Any) -> None:
    node_id, input_name = bindings[binding_name]
    node = workflow.get(node_id)
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise KeyError(f"Workflow node {node_id} for {binding_name} not found.")
    node["inputs"][input_name] = value


def set_optional_input(
    workflow: dict[str, Any],
    bindings: dict[str, tuple[str, str]],
    binding_name: str,
    value: Any,
) -> None:
    if binding_name in bindings:
        set_input(workflow, bindings, binding_name, value)


def lora_syntax(loras: list[dict[str, Any]]) -> str:
    parts = []
    for lora in loras:
        strength = lora.get("strength", 0.7)
        clip = lora.get("clipStrength", strength)
        if float(clip) == float(strength):
            parts.append(f"<lora:{lora['name']}:{strength}>")
        else:
            parts.append(f"<lora:{lora['name']}:{strength}:{clip}>")
    return " ".join(parts)


def parse_lora_spec(value: str) -> dict[str, Any]:
    parts = value.split(":")
    name = parts[0].strip()
    strength = float(parts[1]) if len(parts) > 1 and parts[1] else 0.7
    clip = float(parts[2]) if len(parts) > 2 and parts[2] else strength
    return {"name": name, "strength": strength, "clipStrength": clip, "active": True}


def submit_prompt(comfyui_url: str, workflow: dict[str, Any]) -> str:
    payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{comfyui_url.rstrip('/')}/prompt",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return prompt_id: {result}")
    return str(prompt_id)


def wait_for_history(comfyui_url: str, prompt_id: str, *, timeout: int = 1800, interval: float = 2.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    url = f"{comfyui_url.rstrip('/')}/history/{prompt_id}"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                history = json.loads(response.read().decode("utf-8"))
            if prompt_id in history:
                return history[prompt_id]
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
