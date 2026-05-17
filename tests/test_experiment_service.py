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
            "generation": {"checkpoint": "model.safetensors", "steps": 22, "width": 832, "height": 1216},
        }
    )

    assert len(preview["prompt_variants"]) == 3
    assert len(preview["lora_combos"]) == 7
    assert preview["summary"]["total"] == 3 * 7 * 3 * 2
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

    pair_case = next(case for case in preview["cases"] if case["lora_combo_id"].startswith("pair_") and case["strength"] == 0.8)
    assert [lora["strength"] for lora in pair_case["models"]["loras"]] == [0.8, 0.8]
    assert [lora["clipStrength"] for lora in pair_case["models"]["loras"]] == [0.8, 0.8]


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
    assert service.list_runs()[0]["run_id"] == run["run_id"]


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
        {"name": "a.safetensors", "strength": 0.6, "clipStrength": 0.6, "active": True},
        {"name": "b.safetensors", "strength": 0.6, "clipStrength": 0.6, "active": True},
    ]
    assert workflow["7"]["inputs"]["seed"] == 123


def _fake_get_artwork(artwork_id: str):
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
