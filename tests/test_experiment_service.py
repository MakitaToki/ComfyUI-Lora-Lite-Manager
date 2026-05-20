from __future__ import annotations

from pathlib import Path

from py.experiment import service


def test_preview_expands_baseline_single_and_pair_lora_combos(monkeypatch):
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)

    preview = service.build_experiment_preview(
        {
            "main_artwork": {"id": "main"},
            "visual_references": [{"id": "ref1"}, {"id": "ref2"}],
            "lora_matrix": [
                {"name": "a.safetensors", "strengths": [0.4, 0.6, 0.8]},
                {"name": "b.safetensors", "strengths": [0.4, 0.6, 0.8]},
                {"name": "c.safetensors", "strengths": [0.4, 0.6, 0.8]},
            ],
            "seeds": [123, 456],
            "generation": {
                "checkpoint": "model.safetensors",
                "steps": 22,
                "sampler": "dpmpp_2m",
                "scheduler": "karras",
                "width": 832,
                "height": 1216,
            },
        }
    )

    assert len(preview["prompt_variants"]) == 3
    assert len(preview["lora_combos"]) == 7
    assert preview["summary"]["total"] == 3 * 7 * 1 * 2
    assert preview["cases"][0]["generation"]["sampler"] == "dpmpp_2m"
    assert preview["cases"][0]["generation"]["scheduler"] == "karras"
    assert preview["lora_combos"][0]["id"] == "baseline_no_lora"
    assert any(combo["label"] == "a.safetensors + b.safetensors" for combo in preview["lora_combos"])


def test_pair_combo_uses_synchronized_strength(monkeypatch):
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)

    preview = service.build_experiment_preview(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [
                {"name": "a.safetensors", "strengths": [0.4, 0.8]},
                {"name": "b.safetensors", "strengths": [0.4, 0.8]},
            ],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        }
    )

    pair_case = next(case for case in preview["cases"] if case["lora_combo_id"].startswith("pair_") and case["strength"] == 1.0)
    assert [lora["strength"] for lora in pair_case["models"]["loras"]] == [1.0, 1.0]
    assert [lora["clipStrength"] for lora in pair_case["models"]["loras"]] == [1.0, 1.0]


def test_source_denoise_is_not_applied_to_text_to_image_workflow(monkeypatch):
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)

    preview = service.build_experiment_preview(
        {
            "main_artwork": {
                "id": "main",
                "source_generation": {
                    "workflow_fields": {"cfg": 4.5, "clip_skip": 2, "denoise": 0.47},
                },
            },
            "lora_matrix": [],
            "seeds": [123],
            "generation": {
                "checkpoint": "model.safetensors",
                "source_artwork": {
                    "enabled": True,
                    "apply_fields": ["cfg", "clip_skip", "denoise"],
                },
            },
        }
    )

    generation = preview["cases"][0]["generation"]
    assert generation["cfg"] == 4.5
    assert generation["clip_skip"] == 2
    assert generation["denoise"] == 1


def test_lora_trigger_words_are_appended_to_case_prompt(monkeypatch):
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)

    preview = service.build_experiment_preview(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [
                {"name": "Denia-10.safetensors", "trigger_words": ["Denia"]},
            ],
            "fixed_loras": [
                {
                    "name": "Denia-10.safetensors",
                    "strength": 1.0,
                    "clipStrength": 1.0,
                    "applies_to": ["role", "subject"],
                }
            ],
            "visual_references": [{"id": "ref1", "usage": "subject"}],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        }
    )

    case = next(item for item in preview["cases"] if item["lora_combo_id"] == "baseline_no_lora")
    assert "Denia" in case["prompt"]["positive"]
    assert case["models"]["loras"][0]["trigger_words"] == ["Denia"]


def test_prompt_variant_replaces_main_red_box_terms_by_reference_usage(monkeypatch):
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)

    preview = service.build_experiment_preview(
        {
            "main_artwork": {"id": "graffiti_keqing"},
            "visual_references": [
                {"id": "ref_character", "usage": "参考角色/主体"},
                {"id": "ref_composition", "usage": "参考构图"},
            ],
            "lora_matrix": [{"name": "a.safetensors", "strengths": [0.6]}],
            "seeds": [123],
        }
    )

    role_variant = next(item for item in preview["prompt_variants"] if item["reference_patch"]["role"] == "subject")
    composition_variant = next(item for item in preview["prompt_variants"] if item["reference_patch"]["role"] == "composition")
    combined_variant = next(item for item in preview["prompt_variants"] if item["reference_patch"]["role"] == "subject+composition")

    assert "silver hair idol" in role_variant["positive"]
    assert "exposed shoulders" not in role_variant["positive"]
    assert "detailed jewelry" not in role_variant["positive"]
    assert role_variant["reference_patch"]["matched_terms"] == ["detailed jewelry", "exposed shoulders"]

    assert "low angle rooftop view" in composition_variant["positive"]
    assert "graffiti brick wall background" not in composition_variant["positive"]
    assert "half body portrait" not in composition_variant["positive"]
    assert "center composition" not in composition_variant["positive"]

    assert "silver hair idol" in combined_variant["positive"]
    assert "low angle rooftop view" in combined_variant["positive"]
    assert "exposed shoulders" not in combined_variant["positive"]
    assert "center composition" not in combined_variant["positive"]


def test_danbooru_prompt_keeps_unmatched_terms(monkeypatch):
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)
    monkeypatch.setattr(service, "_canonical_tag", lambda term: "1girl" if term == "girl" else "")

    preview = service.build_experiment_preview(
        {
            "main_artwork": {"id": "main"},
            "visual_references": [{"id": "ref_unmatched"}],
            "lora_matrix": [{"name": "a.safetensors", "strengths": [0.4]}],
            "seeds": [123],
        }
    )

    variant = next(item for item in preview["prompt_variants"] if item["id"] == "tag_variant_1")
    assert "1girl" in variant["tags"]
    assert "中文词" in variant["unmatched_terms"]


def test_run_storage_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "experiments.sqlite3")
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)

    run = service.create_run(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [{"name": "a.safetensors", "strengths": [0.4]}],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        },
        submit=False,
    )

    loaded = service.get_run(run["run_id"])
    assert loaded is not None
    assert loaded["run_id"] == run["run_id"]
    assert loaded["preview"]["summary"]["total"] == 2
    assert [item["status"] for item in loaded["submissions"]] == ["pending", "pending"]
    assert service.list_runs()[0]["run_id"] == run["run_id"]


def test_submit_run_step_persists_incremental_queue_progress(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "experiments.sqlite3")
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)
    monkeypatch.setattr(service, "read_json", lambda _path: {"workflow": True})
    monkeypatch.setattr(service, "patch_workflow", lambda workflow, case: {**workflow, "case": case["case_id"]})
    submitted = []

    def fake_submit_prompt(_url, workflow):
        submitted.append(workflow["case"])
        return f"prompt-{len(submitted)}"

    monkeypatch.setattr(service, "submit_prompt", fake_submit_prompt)

    run = service.create_run(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [{"name": "a.safetensors", "strengths": [0.4]}],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        },
        submit=False,
    )

    first = service.submit_run_step(run["run_id"], batch_size=1)
    assert first is not None
    assert [item["status"] for item in first["submissions"]] == ["queued", "pending"]
    assert first["status"] == "submitting"

    second = service.submit_run_step(run["run_id"], batch_size=1)
    assert second is not None
    assert [item["status"] for item in second["submissions"]] == ["queued", "queued"]
    assert second["status"] == "queued"
    assert [item["prompt_id"] for item in second["submissions"]] == ["prompt-1", "prompt-2"]


def test_submit_run_step_records_case_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "experiments.sqlite3")
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)
    monkeypatch.setattr(service, "read_json", lambda _path: {"workflow": True})
    monkeypatch.setattr(service, "patch_workflow", lambda workflow, case: workflow)
    monkeypatch.setattr(service, "submit_prompt", lambda _url, _workflow: (_ for _ in ()).throw(RuntimeError("queue down")))

    run = service.create_run(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [{"name": "a.safetensors", "strengths": [0.4]}],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        },
        submit=False,
    )

    result = service.submit_run_step(run["run_id"], batch_size=2)
    assert result is not None
    assert result["status"] == "error"
    assert [item["status"] for item in result["submissions"]] == ["error", "error"]
    assert [item["stage"] for item in result["submissions"]] == ["prompt", "prompt"]
    assert all(item["error_type"] == "unknown" for item in result["submissions"])
    assert all("queue down" in item["error_detail"] for item in result["submissions"])


def test_submit_run_step_records_partial_failure_diagnostics(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "experiments.sqlite3")
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)
    monkeypatch.setattr(service, "read_json", lambda _path: {"workflow": True})
    monkeypatch.setattr(service, "patch_workflow", lambda workflow, case: {**workflow, "case": case["case_id"]})
    submitted = []

    def fake_submit_prompt(_url, workflow):
        submitted.append(workflow["case"])
        if len(submitted) == 2:
            raise RuntimeError("ComfyUI /prompt failed with HTTP 400: missing checkpoint")
        return f"prompt-{len(submitted)}"

    monkeypatch.setattr(service, "submit_prompt", fake_submit_prompt)

    run = service.create_run(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [{"name": "a.safetensors", "strengths": [0.4]}],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        },
        submit=False,
    )

    result = service.submit_run_step(run["run_id"], batch_size=2)
    assert result is not None
    assert result["status"] == "queued"
    assert [item["status"] for item in result["submissions"]] == ["queued", "error"]
    failed = result["submissions"][1]
    assert failed["stage"] == "prompt"
    assert failed["error_type"] == "comfyui_http"
    assert "missing checkpoint" in failed["error_detail"]


def test_refresh_run_records_history_diagnostics(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "experiments.sqlite3")
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)
    monkeypatch.setattr(service, "read_json", lambda _path: {"workflow": True})
    monkeypatch.setattr(service, "patch_workflow", lambda workflow, case: workflow)
    monkeypatch.setattr(service, "submit_prompt", lambda _url, _workflow: "prompt-1")
    monkeypatch.setattr(service, "_fetch_history", lambda _url, _prompt_id: (_ for _ in ()).throw(TimeoutError("history timed out")))

    run = service.create_run(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        },
        submit=False,
    )
    queued = service.submit_run_step(run["run_id"], batch_size=1)
    assert queued is not None

    refreshed = service.refresh_run(run["run_id"])
    assert refreshed is not None
    failed = refreshed["submissions"][0]
    assert failed["status"] == "error"
    assert failed["stage"] == "history"
    assert failed["error_type"] == "connection"
    assert "history timed out" in failed["error_detail"]


def test_refresh_run_marks_running_from_comfyui_queue(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "experiments.sqlite3")
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)
    monkeypatch.setattr(service, "read_json", lambda _path: {"workflow": True})
    monkeypatch.setattr(service, "patch_workflow", lambda workflow, case: workflow)
    monkeypatch.setattr(service, "submit_prompt", lambda _url, _workflow: "prompt-1")
    monkeypatch.setattr(service, "_fetch_history", lambda _url, _prompt_id: None)
    monkeypatch.setattr(service, "_fetch_queue", lambda _url: {"queue_running": [[1, "prompt-1", {}]], "queue_pending": []})

    run = service.create_run(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        },
        submit=False,
    )
    queued = service.submit_run_step(run["run_id"], batch_size=1)
    assert queued is not None

    refreshed = service.refresh_run(run["run_id"])
    assert refreshed is not None
    assert refreshed["status"] == "running"
    assert refreshed["submissions"][0]["status"] == "running"


def test_workflow_patch_receives_multiple_loras(monkeypatch):
    monkeypatch.setattr(service, "get_artwork", _fake_get_artwork)
    preview = service.build_experiment_preview(
        {
            "main_artwork": {"id": "main"},
            "lora_matrix": [
                {"name": "a.safetensors", "strengths": [0.6]},
                {"name": "b.safetensors", "strengths": [0.6]},
            ],
            "seeds": [123],
            "generation": {"checkpoint": "model.safetensors"},
        }
    )
    pair_case = next(case for case in preview["cases"] if case["lora_combo_id"].startswith("pair_"))

    workflow = service.patch_workflow(service.read_json(service.DEFAULT_WORKFLOW), pair_case)

    assert workflow["3"]["inputs"]["loras"]["__value__"] == [
        {"name": "a.safetensors", "strength": 1.0, "clipStrength": 1.0, "active": True, "trigger_words": []},
        {"name": "b.safetensors", "strength": 1.0, "clipStrength": 1.0, "active": True, "trigger_words": []},
    ]
    assert workflow["7"]["inputs"]["seed"] == 123


def _fake_get_artwork(artwork_id: str):
    graffiti_items = {
        "graffiti_keqing": {
            "id": "graffiti_keqing",
            "positive_prompt": (
                "detailed jewelry, exposed shoulders, graffiti brick wall background, street fashion, urban style, "
                "cyberpunk aesthetic, vibrant colors, digital art, half body portrait, center composition"
            ),
            "negative_prompt": "",
            "raw_tags": [],
            "retrieval": {},
            "visual_structure": {
                "subject": "anime girl, cat ears, keqing genshin impact, detailed jewelry, exposed shoulders",
                "composition": "graffiti brick wall background, half body portrait, center composition, neon graffiti",
                "color_palette": "vibrant colors",
                "mood": "street fashion, urban style, cyberpunk aesthetic, digital art, sweet cool style, night city vibes",
                "style_booster": "sweet cool style, night city vibes, high contrast lighting",
            },
            "design_language": {},
            "meta": {"title": "Street graffiti Keqing"},
        },
        "ref_character": {
            "id": "ref_character",
            "positive_prompt": "",
            "negative_prompt": "",
            "raw_tags": [],
            "retrieval": {},
            "visual_structure": {
                "subject": "silver hair idol, blue stage dress, moon hair ornament",
            },
            "design_language": {},
            "meta": {"title": "Character Reference"},
        },
        "ref_composition": {
            "id": "ref_composition",
            "positive_prompt": "",
            "negative_prompt": "",
            "raw_tags": [],
            "retrieval": {},
            "visual_structure": {
                "composition": "low angle rooftop view, diagonal composition, wide city skyline",
            },
            "design_language": {},
            "meta": {"title": "Composition Reference"},
        },
    }
    if artwork_id in graffiti_items:
        return graffiti_items[artwork_id]

    items = {
        "main": {
            "id": "main",
            "positive_prompt": "masterpiece, best quality",
            "negative_prompt": "bad quality",
            "raw_tags": ["solo"],
            "retrieval": {},
            "visual_structure": {},
            "design_language": {},
            "meta": {"title": "Main"},
        },
        "ref1": {
            "id": "ref1",
            "positive_prompt": "",
            "negative_prompt": "",
            "raw_tags": ["girl", "long hair"],
            "retrieval": {"keywords_en": ["blue eyes"]},
            "visual_structure": {},
            "design_language": {},
            "meta": {"title": "Ref 1"},
        },
        "ref2": {
            "id": "ref2",
            "positive_prompt": "",
            "negative_prompt": "",
            "raw_tags": ["cat ears"],
            "retrieval": {},
            "visual_structure": {},
            "design_language": {},
            "meta": {"title": "Ref 2"},
        },
        "ref_unmatched": {
            "id": "ref_unmatched",
            "positive_prompt": "",
            "negative_prompt": "",
            "raw_tags": ["girl", "中文词"],
            "retrieval": {},
            "visual_structure": {},
            "design_language": {},
            "meta": {"title": "Ref Unmatched"},
        },
    }
    return items.get(artwork_id)
