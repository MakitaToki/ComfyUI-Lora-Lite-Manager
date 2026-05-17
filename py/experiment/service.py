from __future__ import annotations

from datetime import datetime
import itertools
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from ..collection.storage import get_artwork
from ..config import PLUGIN_ROOT

try:
    from tools.run_advanced_v34_experiment import DEFAULT_WORKFLOW, outputs_from_history, patch_workflow, read_json, submit_prompt
except ImportError:  # pragma: no cover - package import when loaded as a ComfyUI custom node
    from ...tools.run_advanced_v34_experiment import DEFAULT_WORKFLOW, outputs_from_history, patch_workflow, read_json, submit_prompt


EXPERIMENT_DIR = PLUGIN_ROOT / "data" / "experiments"
DB_PATH = EXPERIMENT_DIR / "experiments.sqlite3"
DEFAULT_NEGATIVE = "bad quality, worst quality, sketch, bad hands, bad anatomy, watermark, signature"
DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"


def build_experiment_preview(recipe: dict[str, Any]) -> dict[str, Any]:
    main = _artwork_from_ref(recipe.get("main_artwork"))
    if main is None:
        return {
            "format": "lora_lite_experiment_preview.v1",
            "summary": {"total": 0, "ready": 0, "draft": 1, "warning": "Select a main artwork first."},
            "prompt_variants": [],
            "lora_combos": [],
            "strengths": [],
            "seeds": [],
            "cases": [],
        }

    refs = [_artwork_from_ref(ref) for ref in recipe.get("visual_references", []) if isinstance(ref, dict)]
    refs = [ref for ref in refs if ref is not None]
    prompt_mode = str(recipe.get("prompt_mode") or "danbooru").strip().lower()
    prompt_variants = _prompt_variants(main, refs, prompt_mode)
    lora_combos = _lora_combos(recipe.get("lora_matrix", []))
    strengths = _strengths(recipe.get("lora_matrix", []))
    seeds = _seeds(recipe.get("seeds", []))
    generation = _generation(recipe.get("generation", {}))

    cases: list[dict[str, Any]] = []
    for variant, combo, strength, seed in itertools.product(prompt_variants, lora_combos, strengths, seeds):
        loras = [
            {
                "name": lora["name"],
                "strength": strength,
                "clipStrength": strength,
                "active": True,
            }
            for lora in combo["loras"]
        ]
        case_id = _case_id(variant["id"], combo["id"], strength, seed)
        cases.append(
            {
                "case_id": case_id,
                "compile_status": "ready",
                "prompt_variant_id": variant["id"],
                "prompt_variant_label": variant["label"],
                "lora_combo_id": combo["id"],
                "lora_combo_label": combo["label"],
                "strength": strength,
                "seed": seed,
                "source_artwork_ids": [main.get("id", "")],
                "prompt": {
                    "positive": variant["positive"],
                    "negative": variant["negative"],
                    "tags": variant["tags"],
                    "unmatched_terms": variant["unmatched_terms"],
                    "mode": prompt_mode,
                },
                "models": {
                    "checkpoint": generation["checkpoint"],
                    "loras": loras,
                },
                "generation": {
                    "seed": seed,
                    "steps": generation["steps"],
                    "cfg": generation["cfg"],
                    "sampler": generation["sampler"],
                    "scheduler": generation["scheduler"],
                    "denoise": generation["denoise"],
                    "width": generation["width"],
                    "height": generation["height"],
                    "clip_skip": generation["clip_skip"],
                    "batch_size": generation["batch_size"],
                },
                "output": {
                    "filename_prefix": f"lora_lite_exp_{case_id}",
                },
            }
        )

    warning = ""
    if len(cases) > 120:
        warning = f"This experiment will generate {len(cases)} images."
    return {
        "format": "lora_lite_experiment_preview.v1",
        "summary": {
            "total": len(cases),
            "ready": len(cases),
            "draft": 0,
            "warning": warning,
        },
        "prompt_variants": prompt_variants,
        "lora_combos": lora_combos,
        "strengths": strengths,
        "seeds": seeds,
        "cases": cases,
    }


def create_run(recipe: dict[str, Any], *, comfyui_url: str = DEFAULT_COMFYUI_URL, submit: bool = True) -> dict[str, Any]:
    init_db()
    preview = build_experiment_preview(recipe)
    run_id = "run_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    now = _now()
    status = "draft"
    submissions = _initial_submissions(preview)

    _insert_run(
        {
            "run_id": run_id,
            "status": status,
            "created_at": now,
            "updated_at": now,
            "recipe": recipe,
            "preview": preview,
            "submissions": submissions,
            "comfyui_url": comfyui_url,
            "workflow": str(DEFAULT_WORKFLOW),
        }
    )
    if submit and preview["cases"]:
        while True:
            run = submit_run_step(run_id, batch_size=1)
            if not run or run["status"] in {"queued", "completed", "error"}:
                break
    return get_run(run_id) or {}


def submit_run_step(run_id: str, *, batch_size: int = 1) -> dict[str, Any] | None:
    run = get_run(run_id)
    if run is None:
        return None

    submissions = _ensure_submission_plan(run)
    pending = [item for item in submissions if item.get("status") == "pending"]
    if not pending:
        status = _run_status_from_submissions(submissions)
        _update_run(run_id, status=status, submissions=submissions)
        return get_run(run_id)

    try:
        workflow = read_json(DEFAULT_WORKFLOW)
    except Exception as exc:
        for submission in pending:
            _mark_submission_error(submission, exc, stage="workflow")
        _update_run(run_id, status="error", submissions=_strip_cases(submissions))
        return get_run(run_id)

    status = "submitting"
    for submission in pending[: max(1, batch_size)]:
        try:
            case = submission.get("case") or _case_by_id(run, submission.get("case_id"))
            patched = patch_workflow(workflow, case)
        except Exception as exc:
            _mark_submission_error(submission, exc, stage="workflow")
            continue
        try:
            prompt_id = submit_prompt(run["comfyui_url"], patched)
            submission.update({"prompt_id": prompt_id, "status": "queued", "stage": "queue", "outputs": []})
            for key in ("error", "error_type", "error_message", "error_detail"):
                submission.pop(key, None)
        except Exception as exc:
            _mark_submission_error(submission, exc, stage="prompt")

    if not any(item.get("status") == "pending" for item in submissions):
        status = _run_status_from_submissions(submissions)
    _update_run(run_id, status=status, submissions=_strip_cases(submissions))
    return get_run(run_id)


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT run_id, status, created_at, updated_at, preview_json, submissions_json, comfyui_url
            FROM experiment_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [_run_summary(row) for row in rows]


def get_run(run_id: str) -> dict[str, Any] | None:
    init_db()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM experiment_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return _deserialize_run(row)


def refresh_run(run_id: str) -> dict[str, Any] | None:
    run = get_run(run_id)
    if run is None:
        return None

    changed = False
    all_done = bool(run["submissions"])
    any_error = False
    for submission in run["submissions"]:
        prompt_id = submission.get("prompt_id")
        if submission.get("status") in {"pending", "completed"} or not prompt_id:
            any_error = any_error or submission.get("status") == "error"
            all_done = all_done and submission.get("status") == "completed"
            continue
        try:
            history = _fetch_history(run["comfyui_url"], str(prompt_id))
            if history:
                submission["history"] = history
                submission["outputs"] = outputs_from_history(history)
                submission["status"] = "completed"
                submission["stage"] = "completed"
                for key in ("error", "error_type", "error_message", "error_detail"):
                    submission.pop(key, None)
                changed = True
            else:
                all_done = False
        except Exception as exc:
            _mark_submission_error(submission, exc, stage="history")
            any_error = True
            changed = True

    status = _run_status_from_submissions(run["submissions"]) if run["submissions"] else run["status"]
    if status == "queued" and any(submission.get("status") == "completed" for submission in run["submissions"]):
        status = "running"
    if changed or status != run["status"]:
        _update_run(run_id, status=status, submissions=_strip_cases(run["submissions"]))
    return get_run(run_id)


def init_db(db_path: Path | None = None) -> None:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(path)) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    recipe_json TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    submissions_json TEXT NOT NULL DEFAULT '[]',
                    comfyui_url TEXT NOT NULL,
                    workflow TEXT NOT NULL
                )
                """
            )


def _prompt_variants(main: dict[str, Any], refs: list[dict[str, Any]], prompt_mode: str) -> list[dict[str, Any]]:
    base_positive = _string(main.get("positive_prompt")).strip()
    base_negative = _string(main.get("negative_prompt")).strip() or DEFAULT_NEGATIVE
    variants = [
        {
            "id": "base_prompt",
            "label": "Base prompt",
            "positive": base_positive,
            "negative": base_negative,
            "tags": _split_terms(base_positive),
            "unmatched_terms": [],
            "source_artwork_id": main.get("id", ""),
            "mode": prompt_mode,
        }
    ]
    for index, ref in enumerate(refs, start=1):
        compiled = _compile_reference_terms(ref, prompt_mode)
        if not compiled["prompt"]:
            continue
        variants.append(
            {
                "id": f"tag_variant_{index}",
                "label": _title(ref) or f"Tag variant {index}",
                "positive": ", ".join(part for part in [base_positive, compiled["prompt"]] if part),
                "negative": _string(ref.get("negative_prompt")).strip() or base_negative,
                "tags": compiled["tags"],
                "unmatched_terms": compiled["unmatched_terms"],
                "source_artwork_id": ref.get("id", ""),
                "mode": prompt_mode,
            }
        )
    return variants


def _compile_reference_terms(item: dict[str, Any], prompt_mode: str) -> dict[str, Any]:
    terms = _reference_terms(item)
    if prompt_mode == "natural":
        clean = [term for term in terms if term]
        return {"prompt": ", ".join(dict.fromkeys(clean)), "tags": clean, "unmatched_terms": []}

    tags: list[str] = []
    unmatched: list[str] = []
    for term in terms:
        canonical = _canonical_tag(term)
        if canonical:
            tags.append(canonical)
        elif term and term.isascii():
            unmatched.append(term)
        elif term:
            unmatched.append(term)
    tags = list(dict.fromkeys(tags))
    return {"prompt": ", ".join(tags), "tags": tags, "unmatched_terms": unmatched}


def _canonical_tag(term: str) -> str:
    text = _normalize_term(term)
    if not text or not text.isascii():
        return ""
    try:
        from py.services.tag_fts_index import get_tag_fts_index

        results = get_tag_fts_index().search(text, limit=5)
        for result in results:
            tag = str(result.get("tag_name", ""))
            if tag.lower() == text.lower() or str(result.get("matched_alias", "")).lower() == text.lower():
                return tag
        if results and results[0].get("is_exact_prefix"):
            return str(results[0].get("tag_name", ""))
    except Exception:
        pass
    return text if _looks_like_tag(text) else ""


def _reference_terms(item: dict[str, Any]) -> list[str]:
    retrieval = item.get("retrieval") if isinstance(item.get("retrieval"), dict) else {}
    visual = item.get("visual_structure") if isinstance(item.get("visual_structure"), dict) else {}
    design = item.get("design_language") if isinstance(item.get("design_language"), dict) else {}
    terms: list[str] = []
    terms.extend(_string_list(item.get("raw_tags")))
    terms.extend(_string_list(retrieval.get("keywords_en")))
    terms.extend(_string_list(retrieval.get("keywords_zh")))
    terms.extend(_split_terms(_string(item.get("user_notes"))))
    for value in [visual.get("subject"), visual.get("composition"), visual.get("lighting"), visual.get("mood")]:
        terms.extend(_split_terms(value))
    for value in [design.get("color"), design.get("layout"), design.get("imagery"), design.get("post_process")]:
        terms.extend(_split_terms(value))
    return [term for term in dict.fromkeys(_normalize_term(term) for term in terms) if term]


def _lora_combos(loras_raw: Any) -> list[dict[str, Any]]:
    loras = []
    for item in loras_raw if isinstance(loras_raw, list) else []:
        name = _string(item.get("name")).strip()
        if name:
            loras.append({"name": name, "notes": _string(item.get("notes")), "trigger_words": _string_list(item.get("trigger_words"))})

    combos = [{"id": "baseline_no_lora", "label": "No LoRA", "loras": []}]
    for lora in loras:
        combos.append({"id": "single_" + _slug(lora["name"]), "label": lora["name"], "loras": [lora]})
    for left, right in itertools.combinations(loras, 2):
        combo_loras = [left, right]
        combos.append(
            {
                "id": "pair_" + _slug(left["name"]) + "__" + _slug(right["name"]),
                "label": f"{left['name']} + {right['name']}",
                "loras": combo_loras,
            }
        )
    return combos


def _strengths(loras_raw: Any) -> list[float]:
    values: list[float] = []
    for item in loras_raw if isinstance(loras_raw, list) else []:
        for value in item.get("strengths", []) if isinstance(item.get("strengths"), list) else []:
            try:
                values.append(round(float(value), 3))
            except (TypeError, ValueError):
                pass
    return sorted(dict.fromkeys(values)) or [0.7]


def _seeds(raw: Any) -> list[int]:
    values = []
    for value in raw if isinstance(raw, list) else []:
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            pass
    return values or [-1]


def _generation(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "checkpoint": _string(source.get("checkpoint")).strip(),
        "steps": _int(source.get("steps"), 22),
        "cfg": _float(source.get("cfg"), 6),
        "sampler": _string(source.get("sampler") or "euler_ancestral"),
        "scheduler": _string(source.get("scheduler") or "normal"),
        "denoise": _float(source.get("denoise"), 1),
        "width": _int(source.get("width"), 832),
        "height": _int(source.get("height"), 1216),
        "clip_skip": _int(source.get("clip_skip"), 2),
        "batch_size": _int(source.get("batch_size"), 1),
    }


def _initial_submissions(preview: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"case_id": case.get("case_id", ""), "status": "pending", "stage": "pending", "outputs": []}
        for case in preview.get("cases", [])
        if case.get("case_id")
    ]


def _ensure_submission_plan(run: dict[str, Any]) -> list[dict[str, Any]]:
    submissions = run.get("submissions") if isinstance(run.get("submissions"), list) else []
    if submissions:
        return submissions
    return _initial_submissions(run.get("preview") if isinstance(run.get("preview"), dict) else {})


def _case_by_id(run: dict[str, Any], case_id: Any) -> dict[str, Any]:
    for case in run.get("preview", {}).get("cases", []):
        if case.get("case_id") == case_id:
            return case
    raise ValueError(f"Experiment case not found: {case_id}")


def _strip_cases(submissions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in submission.items() if key != "case"} for submission in submissions]


def _mark_submission_error(submission: dict[str, Any], exc: Exception, *, stage: str) -> None:
    detail = str(exc)
    error_type, message = _classify_submission_error(detail, stage=stage)
    submission.update(
        {
            "status": "error",
            "stage": stage,
            "error": message,
            "error_type": error_type,
            "error_message": message,
            "error_detail": detail,
            "outputs": [],
        }
    )


def _classify_submission_error(detail: str, *, stage: str) -> tuple[str, str]:
    text = detail.lower()
    if "did not return prompt_id" in text:
        return "missing_prompt_id", "ComfyUI did not return a prompt_id."
    if "timed out" in text or "timeout" in text or "connection" in text or "refused" in text or "urlopen" in text:
        return "connection", "Could not reach ComfyUI or the request timed out."
    if "http" in text or "/prompt failed" in text:
        return "comfyui_http", "ComfyUI rejected the prompt request."
    if stage == "workflow":
        return "workflow", "Failed to build the ComfyUI workflow for this case."
    if stage == "history":
        return "history", "The prompt was submitted, but result history could not be queried."
    return "unknown", "Experiment case failed."


def _run_status_from_submissions(submissions: list[dict[str, Any]]) -> str:
    if not submissions:
        return "draft"
    statuses = [
        "queued" if str(item.get("status") or "pending") == "submitted" else str(item.get("status") or "pending")
        for item in submissions
    ]
    if any(status == "pending" for status in statuses):
        return "submitting" if any(status in {"queued", "completed", "error"} for status in statuses) else "draft"
    if all(status == "completed" for status in statuses):
        return "completed"
    if any(status == "queued" for status in statuses):
        return "queued"
    if any(status == "completed" for status in statuses):
        return "running"
    return "error" if any(status == "error" for status in statuses) else "draft"


def _fetch_history(comfyui_url: str, prompt_id: str) -> dict[str, Any] | None:
    url = f"{comfyui_url.rstrip('/')}/history/{urllib.parse.quote(prompt_id)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return payload.get(prompt_id)


def _insert_run(run: dict[str, Any]) -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO experiment_runs (
                    run_id, status, created_at, updated_at, recipe_json, preview_json,
                    submissions_json, comfyui_url, workflow
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run["status"],
                    run["created_at"],
                    run["updated_at"],
                    json.dumps(run["recipe"], ensure_ascii=False),
                    json.dumps(run["preview"], ensure_ascii=False),
                    json.dumps(run["submissions"], ensure_ascii=False),
                    run["comfyui_url"],
                    run["workflow"],
                ),
            )


def _update_run(run_id: str, *, status: str, submissions: list[dict[str, Any]]) -> None:
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                UPDATE experiment_runs
                SET status = ?, submissions_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (status, json.dumps(submissions, ensure_ascii=False), _now(), run_id),
            )


def _deserialize_run(row: sqlite3.Row) -> dict[str, Any]:
    preview = json.loads(row["preview_json"])
    submissions = json.loads(row["submissions_json"])
    cases_by_id = {case["case_id"]: case for case in preview.get("cases", [])}
    for submission in submissions:
        case = cases_by_id.get(submission.get("case_id"))
        if case:
            submission["case"] = case
        for output in submission.get("outputs", []):
            output["url"] = _output_url(row["comfyui_url"], output)
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "recipe": json.loads(row["recipe_json"]),
        "preview": preview,
        "submissions": submissions,
        "comfyui_url": row["comfyui_url"],
        "workflow": row["workflow"],
    }


def _run_summary(row: sqlite3.Row) -> dict[str, Any]:
    preview = json.loads(row["preview_json"])
    submissions = json.loads(row["submissions_json"])
    completed = sum(1 for item in submissions if item.get("status") == "completed")
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "total": preview.get("summary", {}).get("total", 0),
        "completed": completed,
        "comfyui_url": row["comfyui_url"],
    }


def _output_url(comfyui_url: str, output: dict[str, Any]) -> str:
    query = urllib.parse.urlencode(
        {
            "filename": output.get("filename", ""),
            "subfolder": output.get("subfolder", ""),
            "type": output.get("type", "output"),
        }
    )
    return f"{comfyui_url.rstrip('/')}/view?{query}"


def _artwork_from_ref(ref: Any) -> dict[str, Any] | None:
    if not isinstance(ref, dict):
        return None
    artwork_id = _string(ref.get("id")).strip()
    return get_artwork(artwork_id) if artwork_id else None


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _case_id(variant_id: str, combo_id: str, strength: float, seed: int) -> str:
    return f"{_slug(variant_id)}__{_slug(combo_id)}__s{str(strength).replace('.', '_')}__seed{seed}"


def _title(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return _string(meta.get("title") or item.get("user_notes") or item.get("source_id") or item.get("id"))


def _split_terms(value: Any) -> list[str]:
    text = _string(value)
    if not text:
        return []
    separators = [",", "，", "\n", ";", "；"]
    for separator in separators[1:]:
        text = text.replace(separator, separators[0])
    return [_normalize_term(part) for part in text.split(",") if _normalize_term(part)]


def _normalize_term(value: Any) -> str:
    text = _string(value).strip().lower()
    return " ".join(text.replace("_", " ").split()).replace(" ", "_")


def _looks_like_tag(value: str) -> bool:
    return bool(value) and value.isascii() and len(value) <= 80 and "http" not in value.lower()


def _slug(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isascii() and char.isalnum():
            chars.append(char)
        elif char in {"_", "-", ".", " "}:
            chars.append("_")
    return "".join(chars).strip("_")[:64] or "item"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_string(item).strip() for item in value if _string(item).strip()]
    if isinstance(value, str):
        return _split_terms(value)
    return []


def _string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
