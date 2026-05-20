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
FIXED_TEST_LORA_STRENGTH = 1.0


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
    fixed_loras = _fixed_loras(recipe.get("fixed_loras", []), trigger_lookup=_lora_trigger_lookup(recipe.get("lora_matrix", [])))
    source_generation = _source_generation(recipe.get("main_artwork"), main)
    generation = _generation(recipe.get("generation", {}), source_generation)
    workflow_support = _source_generation_workflow_support(source_generation)

    cases: list[dict[str, Any]] = []
    for variant, combo, strength, seed in itertools.product(prompt_variants, lora_combos, strengths, seeds):
        variant_fixed_loras = _fixed_loras_for_variant(fixed_loras, variant)
        loras = variant_fixed_loras + [
            {
                "name": lora["name"],
                "strength": strength,
                "clipStrength": strength,
                "active": True,
                "role": "test",
                "trigger_words": lora.get("trigger_words", []),
            }
            for lora in combo["loras"]
        ]
        positive = _positive_with_lora_triggers(variant["positive"], loras)
        case_id = _case_id(variant["id"], combo["id"], strength, seed)
        cases.append(
            {
                "case_id": case_id,
                "compile_status": "ready",
                "prompt_variant_id": variant["id"],
                "prompt_variant_label": variant["label"],
                "lora_combo_id": combo["id"],
                "lora_combo_label": combo["label"],
                "fixed_loras": variant_fixed_loras,
                "strength": strength,
                "seed": seed,
                "source_artwork_ids": [main.get("id", "")],
                "prompt": {
                    "positive": positive,
                    "negative": variant["negative"],
                    "tags": _split_terms(positive),
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
                "source_generation": source_generation,
                "workflow_support": workflow_support,
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
        "source_generation": source_generation,
        "workflow_support": workflow_support,
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
    queue = _fetch_queue(run["comfyui_url"])
    running_prompt_ids = _queue_prompt_ids(queue.get("queue_running", []))
    pending_prompt_ids = _queue_prompt_ids(queue.get("queue_pending", []))
    for submission in run["submissions"]:
        prompt_id = submission.get("prompt_id")
        if submission.get("status") in {"pending", "completed"} or not prompt_id:
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
        except Exception as exc:
            _mark_submission_error(submission, exc, stage="history")
            changed = True
            continue
        if history:
            continue
        previous_status = submission.get("status")
        if str(prompt_id) in running_prompt_ids:
            submission["status"] = "running"
            submission["stage"] = "queue"
        elif str(prompt_id) in pending_prompt_ids:
            submission["status"] = "queued"
            submission["stage"] = "queue"
        else:
            submission["status"] = "queued"
            submission["stage"] = "queue"
            submission["diagnostic_message"] = "Prompt has been submitted but is not currently visible in ComfyUI queue or history."
        changed = changed or previous_status != submission.get("status")

    status = _run_status_from_submissions(run["submissions"]) if run["submissions"] else run["status"]
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
    base_terms = _prompt_base_terms(main)
    base_positive = _join_terms(base_terms) or _string(main.get("positive_prompt")).strip()
    base_negative = _string(main.get("negative_prompt")).strip() or DEFAULT_NEGATIVE
    role_ref = _reference_by_usage(refs, "role")
    composition_ref = _reference_by_usage(refs, "composition")
    variants: list[dict[str, Any]] = []

    patches = _reference_patches(main, refs)
    if patches:
        for index, patch in enumerate(patches, start=1):
            positive, matched_terms = _replace_prompt_terms(base_terms, patch["main_terms"], patch["terms"])
            variants.append(
                {
                    "id": f"{patch['role']}_variant_{index}",
                    "label": patch["label"],
                    "positive": positive,
                    "negative": _string(patch["ref"].get("negative_prompt")).strip() or base_negative,
                    "tags": _split_terms(positive),
                    "unmatched_terms": [],
                    "source_artwork_id": patch["ref"].get("id", ""),
                    "reference_patch": {
                        "role": patch["role"],
                        "field": patch["field"],
                        "terms": patch["terms"],
                        "matched_terms": matched_terms,
                    },
                    "mode": prompt_mode,
                }
            )

        if len(patches) > 1:
            positive, matched_by_role = _replace_prompt_terms_for_patches(base_terms, patches)
            variants.append(
                {
                    "id": "_".join(patch["role"] for patch in patches) + "_variant",
                    "label": "Combined reference variant",
                    "positive": positive,
                    "negative": base_negative,
                    "tags": _split_terms(positive),
                    "unmatched_terms": [],
                    "source_artwork_id": ",".join(patch["ref"].get("id", "") for patch in patches if patch["ref"].get("id")),
                    "reference_patch": {
                        "role": "+".join(patch["role"] for patch in patches),
                        "patches": [
                            {
                                "role": patch["role"],
                                "field": patch["field"],
                                "terms": patch["terms"],
                                "matched_terms": matched_by_role.get(patch["role"], []),
                            }
                            for patch in patches
                        ],
                    },
                    "mode": prompt_mode,
                }
            )
        return variants

    role_terms = _reference_field_terms(role_ref, "subject") if role_ref else []
    if role_terms:
        variants.append(
            {
                "id": "role_subject_variant",
                "label": "角色/主体变体",
                "positive": _join_prompt_parts(base_positive, role_terms),
                "negative": _string(role_ref.get("negative_prompt")).strip() or base_negative,
                "tags": role_terms,
                "unmatched_terms": [],
                "source_artwork_id": role_ref.get("id", ""),
                "reference_patch": {"role": "subject", "terms": role_terms},
                "mode": prompt_mode,
            }
        )

    composition_terms = _reference_field_terms(composition_ref, "composition") if composition_ref else []
    if composition_terms:
        variants.append(
            {
                "id": "composition_variant",
                "label": "构图变体",
                "positive": _join_prompt_parts(base_positive, composition_terms),
                "negative": _string(composition_ref.get("negative_prompt")).strip() or base_negative,
                "tags": composition_terms,
                "unmatched_terms": [],
                "source_artwork_id": composition_ref.get("id", ""),
                "reference_patch": {"role": "composition", "terms": composition_terms},
                "mode": prompt_mode,
            }
        )

    if role_terms and composition_terms:
        variants.append(
            {
                "id": "role_subject_composition_variant",
                "label": "角色/主体 + 构图变体",
                "positive": _join_prompt_parts(base_positive, role_terms, composition_terms),
                "negative": base_negative,
                "tags": list(dict.fromkeys(role_terms + composition_terms)),
                "unmatched_terms": [],
                "source_artwork_id": ",".join(
                    item.get("id", "") for item in [role_ref, composition_ref] if item and item.get("id")
                ),
                "reference_patch": {
                    "role": "subject+composition",
                    "subject_terms": role_terms,
                    "composition_terms": composition_terms,
                },
                "mode": prompt_mode,
            }
        )

    if variants:
        return variants

    return [
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
    return variants


def _prompt_base_terms(item: dict[str, Any]) -> list[str]:
    visual = item.get("visual_structure") if isinstance(item.get("visual_structure"), dict) else {}
    terms = _split_prompt_terms(_string(item.get("positive_prompt")))
    terms.extend(_split_prompt_terms(visual.get("style_booster")))
    return _dedupe_terms(terms)


def _reference_patches(main: dict[str, Any], refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for index, ref in enumerate(refs):
        field = _reference_usage_field(ref, index)
        if not field:
            continue
        terms = _reference_prompt_terms(ref, field)
        if not terms:
            continue
        role = _field_role(field)
        patches.append(
            {
                "role": role,
                "field": field,
                "label": _field_label(field),
                "ref": ref,
                "terms": terms,
                "main_terms": _reference_prompt_terms(main, field),
            }
        )
    return patches


def _reference_usage_field(ref: dict[str, Any], index: int) -> str:
    usage = _string(ref.get("usage")).lower()
    aliases = [
        ("subject", ("role", "character", "subject", "\u89d2\u8272", "\u4e3b\u4f53")),
        ("composition", ("composition", "\u6784\u56fe")),
        ("color_palette", ("color", "palette", "\u8272\u5f69", "\u8272\u8c03")),
        ("mood", ("mood", "atmosphere", "\u6c1b\u56f4", "\u60c5\u7eea")),
        ("style_booster", ("style", "\u98ce\u683c")),
    ]
    for field, needles in aliases:
        if any(needle in usage for needle in needles):
            return field
    if "\u4ec5" in usage or "note" in usage:
        return ""
    return "subject" if index == 0 else "composition"


def _reference_prompt_terms(item: dict[str, Any], field: str) -> list[str]:
    visual = item.get("visual_structure") if isinstance(item.get("visual_structure"), dict) else {}
    design = item.get("design_language") if isinstance(item.get("design_language"), dict) else {}
    values: list[Any] = [visual.get(field)]
    if field == "composition":
        values.append(design.get("layout"))
    elif field == "subject":
        values.append(design.get("imagery"))
    elif field == "color_palette":
        values.append(design.get("color"))
    elif field == "style_booster":
        values.append(design.get("post_process"))

    terms: list[str] = []
    for value in values:
        terms.extend(_split_prompt_terms(value))
    if not terms and field in {"subject", "composition"}:
        terms = _reference_terms(item)
    return _dedupe_terms(terms)


def _replace_prompt_terms(base_terms: list[str], main_terms: list[str], ref_terms: list[str]) -> tuple[str, list[str]]:
    main_lookup = {_term_key(term) for term in main_terms}
    output: list[str] = []
    matched: list[str] = []
    inserted = False
    for term in base_terms:
        if _term_key(term) in main_lookup:
            matched.append(term)
            if not inserted:
                output.extend(ref_terms)
                inserted = True
            continue
        output.append(term)
    if not inserted:
        output.extend(ref_terms)
    return _join_terms(_dedupe_terms(output)), _dedupe_terms(matched)


def _replace_prompt_terms_for_patches(base_terms: list[str], patches: list[dict[str, Any]]) -> tuple[str, dict[str, list[str]]]:
    current = list(base_terms)
    matched_by_role: dict[str, list[str]] = {}
    for patch in patches:
        positive, matched = _replace_prompt_terms(current, patch["main_terms"], patch["terms"])
        current = _split_prompt_terms(positive)
        matched_by_role[patch["role"]] = matched
    return _join_terms(current), matched_by_role


def _field_role(field: str) -> str:
    return {
        "subject": "subject",
        "composition": "composition",
        "color_palette": "color",
        "mood": "mood",
        "style_booster": "style",
    }.get(field, field)


def _field_label(field: str) -> str:
    return {
        "subject": "Subject reference variant",
        "composition": "Composition reference variant",
        "color_palette": "Color reference variant",
        "mood": "Mood reference variant",
        "style_booster": "Style reference variant",
    }.get(field, "Reference variant")


def _split_prompt_terms(value: Any) -> list[str]:
    text = _string(value)
    if not text:
        return []
    separators = [",", "\n", ";", "\uff0c", "\u3001"]
    for separator in separators[1:]:
        text = text.replace(separator, separators[0])
    return [" ".join(part.strip().split()) for part in text.split(",") if part.strip()]


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        key = _term_key(term)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def _term_key(term: Any) -> str:
    return _normalize_term(term).replace("_", " ")


def _join_terms(terms: list[str]) -> str:
    return ", ".join(term for term in terms if term)


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


def _reference_by_usage(refs: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    needles = {
        "role": ("角色", "主体", "subject", "character"),
        "composition": ("构图", "composition"),
    }[role]
    for ref in refs:
        usage = _string(ref.get("usage")).lower()
        if any(needle.lower() in usage for needle in needles):
            return ref
    if role == "role" and refs:
        return refs[0]
    if role == "composition" and len(refs) > 1:
        return refs[1]
    return None


def _reference_field_terms(item: dict[str, Any], key: str) -> list[str]:
    visual = item.get("visual_structure") if isinstance(item.get("visual_structure"), dict) else {}
    return list(dict.fromkeys(_split_terms(visual.get(key))))


def _join_prompt_parts(base: str, *term_groups: list[str]) -> str:
    parts = [_string(base).strip()]
    for terms in term_groups:
        text = ", ".join(term for term in terms if term)
        if text:
            parts.append(text)
    return ", ".join(part for part in parts if part)


def _lora_combos(loras_raw: Any) -> list[dict[str, Any]]:
    loras = []
    for item in loras_raw if isinstance(loras_raw, list) else []:
        name = _string(item.get("name")).strip()
        if name:
            loras.append({"name": name, "notes": _string(item.get("notes")), "trigger_words": _string_list(item.get("trigger_words"))})

    combos = [{"id": "baseline_no_lora", "label": "No test LoRA", "loras": []}]
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


def _lora_trigger_lookup(raw: Any) -> dict[str, list[str]]:
    lookup: dict[str, list[str]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = _string(item.get("name")).strip()
        trigger_words = _string_list(item.get("trigger_words"))
        if name and trigger_words:
            lookup[name] = trigger_words
    return lookup


def _fixed_loras(raw: Any, *, trigger_lookup: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    trigger_lookup = trigger_lookup or {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = _string(item.get("name")).strip()
        if not name:
            continue
        strength = _float(item.get("strength"), 1.0)
        applies_to = _string_list(item.get("applies_to")) or ["role", "role+composition"]
        trigger_words = _string_list(item.get("trigger_words")) or trigger_lookup.get(name, [])
        values.append(
            {
                "name": name,
                "strength": strength,
                "clipStrength": _float(item.get("clipStrength"), strength),
                "active": bool(item.get("active", True)),
                "role": _string(item.get("role") or "fixed"),
                "applies_to": applies_to,
                "trigger_words": trigger_words,
            }
        )
    return values


def _fixed_loras_for_variant(loras: list[dict[str, Any]], variant: dict[str, Any]) -> list[dict[str, Any]]:
    patch = variant.get("reference_patch") if isinstance(variant.get("reference_patch"), dict) else {}
    role = _string(patch.get("role"))
    aliases = {
        "subject": {"subject", "role"},
        "subject+composition": {"subject+composition", "role+composition"},
    }.get(role, {role})
    selected: list[dict[str, Any]] = []
    for lora in loras:
        applies_to = lora.get("applies_to") if isinstance(lora.get("applies_to"), list) else []
        if aliases.intersection(set(applies_to)):
            selected.append({key: value for key, value in lora.items() if key != "applies_to"})
    return selected


def _positive_with_lora_triggers(positive: str, loras: list[dict[str, Any]]) -> str:
    terms = _split_prompt_terms(positive)
    for lora in loras:
        if not lora.get("active", True):
            continue
        terms.extend(_string_list(lora.get("trigger_words")))
    return _join_terms(_dedupe_terms(terms))


def _strengths(loras_raw: Any) -> list[float]:
    return [FIXED_TEST_LORA_STRENGTH]


def _seeds(raw: Any) -> list[int]:
    values = []
    for value in raw if isinstance(raw, list) else []:
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            pass
    return values or [-1]


def _generation(raw: Any, source_generation: dict[str, Any] | None = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    generation = {
        "checkpoint": _string(source.get("checkpoint")).strip(),
        "steps": _int(source.get("steps"), 22),
        "cfg": _float(source.get("cfg"), 6),
        "sampler": _normalize_sampler(_string(source.get("sampler") or "euler_ancestral")),
        "scheduler": _normalize_scheduler(_string(source.get("scheduler") or "normal")),
        "denoise": _float(source.get("denoise"), 1),
        "width": _int(source.get("width"), 832),
        "height": _int(source.get("height"), 1216),
        "clip_skip": _int(source.get("clip_skip"), 2),
        "batch_size": _int(source.get("batch_size"), 1),
    }
    policy = source.get("source_artwork") if isinstance(source.get("source_artwork"), dict) else {}
    if policy.get("enabled") and source_generation:
        fields = policy.get("apply_fields") if isinstance(policy.get("apply_fields"), list) else []
        workflow_fields = source_generation.get("workflow_fields") if isinstance(source_generation.get("workflow_fields"), dict) else {}
        for field in fields:
            if field not in workflow_fields:
                continue
            value = workflow_fields[field]
            if field == "sampler":
                generation[field] = _normalize_sampler(_string(value))
            elif field == "scheduler":
                generation[field] = _normalize_scheduler(_string(value))
            elif field in {"steps", "width", "height", "clip_skip", "batch_size"}:
                generation[field] = _int(value, generation[field])
            elif field == "cfg":
                generation[field] = _float(value, generation[field])
    return generation


def _source_generation(recipe_ref: Any, artwork: dict[str, Any]) -> dict[str, Any] | None:
    recipe_source = recipe_ref.get("source_generation") if isinstance(recipe_ref, dict) else None
    if isinstance(recipe_source, dict) and recipe_source.get("workflow_fields"):
        return {
            "source": _string(recipe_source.get("source") or artwork.get("source")),
            "source_url": _string(recipe_source.get("source_url") or artwork.get("source_url")),
            "civitai_meta_id": recipe_source.get("civitai_meta_id"),
            "workflow_fields": _normalize_source_workflow_fields(recipe_source.get("workflow_fields")),
            "carry_fields": _clean_dict(recipe_source.get("carry_fields") if isinstance(recipe_source.get("carry_fields"), dict) else {}),
            "raw_generation": recipe_source.get("raw_generation") if isinstance(recipe_source.get("raw_generation"), dict) else {},
        }

    seed = artwork.get("aigc_seed") if isinstance(artwork.get("aigc_seed"), dict) else {}
    meta = artwork.get("meta") if isinstance(artwork.get("meta"), dict) else {}
    generation = seed or (meta.get("generation") if isinstance(meta.get("generation"), dict) else {})
    if not generation:
        return None
    workflow_fields = _normalize_source_workflow_fields(
        {
            "steps": generation.get("steps") or meta.get("steps"),
            "cfg": generation.get("cfg_scale") or meta.get("cfgScale"),
            "sampler": generation.get("sampler") or meta.get("sampler"),
            "scheduler": generation.get("schedule_type") or generation.get("scheduler") or meta.get("Schedule type"),
            "seed": generation.get("seed") or meta.get("seed"),
            "clip_skip": generation.get("clip_skip") or meta.get("clipSkip"),
            "width": generation.get("width") or meta.get("width"),
            "height": generation.get("height") or meta.get("height"),
            "denoise": generation.get("denoising_strength") or meta.get("Denoising strength"),
        }
    )
    carry_fields = _clean_dict(
        {
            "model": generation.get("model") or meta.get("Model"),
            "model_hash": generation.get("model_hash") or meta.get("Model hash"),
            "hires_steps": generation.get("hires_steps") or meta.get("Hires steps"),
            "hires_upscale": generation.get("hires_upscale") or meta.get("Hires upscale"),
            "hires_upscaler": generation.get("hires_upscaler") or meta.get("Hires upscaler"),
            "hires_cfg": generation.get("hires_cfg_scale") or meta.get("Hires CFG Scale"),
            "token_merge": generation.get("token_merging_ratio") or meta.get("Token merging ratio"),
            "token_merge_hr": generation.get("token_merging_ratio_hr") or meta.get("Token merging ratio hr"),
        }
    )
    return {
        "source": _string(artwork.get("source")),
        "source_url": _string(artwork.get("source_url")),
        "civitai_meta_id": meta.get("civitai_meta_id"),
        "workflow_fields": workflow_fields,
        "carry_fields": carry_fields,
        "raw_generation": meta.get("raw_generation") if isinstance(meta.get("raw_generation"), dict) else generation,
    }


def _normalize_source_workflow_fields(source: Any) -> dict[str, Any]:
    fields = source if isinstance(source, dict) else {}
    sampler = _string(fields.get("sampler")).strip()
    scheduler = _string(fields.get("scheduler")).strip()
    return _clean_dict(
        {
            "steps": _int(fields.get("steps"), None),
            "cfg": _float(fields.get("cfg"), None),
            "sampler": _normalize_sampler(sampler) if sampler else None,
            "scheduler": _normalize_scheduler(scheduler) if scheduler else None,
            "seed": _int(fields.get("seed"), None),
            "clip_skip": _int(fields.get("clip_skip"), None),
            "width": _int(fields.get("width"), None),
            "height": _int(fields.get("height"), None),
            "denoise": _float(fields.get("denoise"), None),
        }
    )


def _source_generation_workflow_support(source_generation: dict[str, Any] | None) -> dict[str, Any]:
    if not source_generation:
        return {"supported_fields": [], "carry_only_fields": [], "unsupported_fields": []}
    workflow_fields = source_generation.get("workflow_fields") if isinstance(source_generation.get("workflow_fields"), dict) else {}
    carry_fields = source_generation.get("carry_fields") if isinstance(source_generation.get("carry_fields"), dict) else {}
    return {
        "supported_fields": sorted(workflow_fields.keys()),
        "carry_only_fields": sorted(carry_fields.keys()),
        "unsupported_fields": sorted(carry_fields.keys()),
    }


def _normalize_sampler(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return {
        "euler_a": "euler_ancestral",
        "euler_ancestral": "euler_ancestral",
    }.get(normalized, normalized or "euler_ancestral")


def _normalize_scheduler(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return {
        "karras": "karras",
        "schedule_type_karras": "karras",
    }.get(normalized, normalized or "normal")


def _clean_dict(source: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if value not in ("", None)}


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
        return "submitting" if any(status in {"queued", "running", "completed", "error"} for status in statuses) else "draft"
    if all(status == "completed" for status in statuses):
        return "completed"
    if any(status == "running" for status in statuses):
        return "running"
    if any(status == "queued" for status in statuses):
        return "queued"
    if any(status == "completed" for status in statuses):
        return "running"
    return "error" if any(status == "error" for status in statuses) else "draft"


def _fetch_queue(comfyui_url: str) -> dict[str, Any]:
    url = f"{comfyui_url.rstrip('/')}/queue"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _queue_prompt_ids(items: Any) -> set[str]:
    prompt_ids: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if isinstance(item, (list, tuple)) and len(item) > 1:
            prompt_ids.add(str(item[1]))
        elif isinstance(item, dict) and item.get("prompt_id"):
            prompt_ids.add(str(item.get("prompt_id")))
    return prompt_ids


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
    running = sum(1 for item in submissions if item.get("status") == "running")
    queued = sum(1 for item in submissions if item.get("status") in {"queued", "submitted"})
    failed = sum(1 for item in submissions if item.get("status") == "error")
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "total": preview.get("summary", {}).get("total", 0),
        "completed": completed,
        "running": running,
        "queued": queued,
        "error": failed,
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
    artwork = get_artwork(artwork_id) if artwork_id else None
    if artwork:
        artwork = {**artwork, "usage": ref.get("usage", artwork.get("usage", ""))}
    return artwork


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
