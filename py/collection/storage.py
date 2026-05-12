from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from ..config import PLUGIN_ROOT


COLLECTION_DIR = PLUGIN_ROOT / "data" / "collection"
DB_PATH = COLLECTION_DIR / "collection.sqlite3"


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db_path)) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artworks (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                asset_type TEXT NOT NULL DEFAULT 'ai_generation_reference',
                source_id TEXT NOT NULL,
                source_url TEXT,
                image_url TEXT,
                preview_path TEXT,
                width INTEGER,
                height INTEGER,
                nsfw TEXT,
                nsfw_level INTEGER,
                creator TEXT,
                positive_prompt TEXT,
                negative_prompt TEXT,
                raw_tags_json TEXT NOT NULL DEFAULT '[]',
                model_refs_json TEXT NOT NULL DEFAULT '[]',
                stats_json TEXT NOT NULL DEFAULT '{}',
                meta_json TEXT NOT NULL DEFAULT '{}',
                visual_structure_json TEXT NOT NULL DEFAULT '{}',
                design_language_json TEXT NOT NULL DEFAULT '{}',
                transfer_json TEXT NOT NULL DEFAULT '{}',
                aigc_seed_json TEXT NOT NULL DEFAULT '{}',
                retrieval_json TEXT NOT NULL DEFAULT '{}',
                user_notes TEXT DEFAULT '',
                created_at TEXT,
                collected_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_artworks_source ON artworks(source, source_id);
                CREATE INDEX IF NOT EXISTS idx_artworks_created_at ON artworks(created_at);

                CREATE VIRTUAL TABLE IF NOT EXISTS artworks_fts USING fts5(
                id UNINDEXED,
                positive_prompt,
                negative_prompt,
                raw_tags,
                creator,
                model_refs
                );
                """
            )
            _ensure_columns(conn)


def upsert_artwork(artwork: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    init_db(db_path)
    with closing(_connect(db_path)) as conn:
        with conn:
            conn.execute(
            """
            INSERT INTO artworks (
                id, source, source_id, source_url, image_url, preview_path,
                asset_type,
                width, height, nsfw, nsfw_level, creator,
                positive_prompt, negative_prompt, raw_tags_json, model_refs_json,
                stats_json, meta_json, visual_structure_json, design_language_json,
                transfer_json, aigc_seed_json, retrieval_json, user_notes,
                created_at, collected_at, updated_at
            )
            VALUES (
                :id, :source, :source_id, :source_url, :image_url, :preview_path,
                :asset_type,
                :width, :height, :nsfw, :nsfw_level, :creator,
                :positive_prompt, :negative_prompt, :raw_tags_json, :model_refs_json,
                :stats_json, :meta_json, :visual_structure_json, :design_language_json,
                :transfer_json, :aigc_seed_json, :retrieval_json, :user_notes,
                :created_at, :collected_at, CURRENT_TIMESTAMP
            )
            ON CONFLICT(id) DO UPDATE SET
                asset_type = excluded.asset_type,
                source_url = excluded.source_url,
                image_url = excluded.image_url,
                preview_path = COALESCE(NULLIF(excluded.preview_path, ''), artworks.preview_path),
                width = excluded.width,
                height = excluded.height,
                nsfw = excluded.nsfw,
                nsfw_level = excluded.nsfw_level,
                creator = excluded.creator,
                positive_prompt = excluded.positive_prompt,
                negative_prompt = excluded.negative_prompt,
                raw_tags_json = excluded.raw_tags_json,
                model_refs_json = excluded.model_refs_json,
                stats_json = excluded.stats_json,
                meta_json = excluded.meta_json,
                visual_structure_json = excluded.visual_structure_json,
                design_language_json = excluded.design_language_json,
                transfer_json = excluded.transfer_json,
                aigc_seed_json = excluded.aigc_seed_json,
                retrieval_json = excluded.retrieval_json,
                user_notes = excluded.user_notes,
                created_at = excluded.created_at,
                collected_at = excluded.collected_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            _serialize(artwork),
            )
            _replace_fts(conn, artwork)
    return get_artwork(str(artwork["id"]), db_path) or artwork


def search_artworks(
    *,
    query: str = "",
    sort: str = "newest",
    limit: int = 60,
    offset: int = 0,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    init_db(db_path)
    query = query.strip()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    where = ""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    join = ""
    if query:
        where = """
        WHERE artworks.positive_prompt LIKE :like
           OR artworks.negative_prompt LIKE :like
           OR artworks.raw_tags_json LIKE :like
           OR artworks.model_refs_json LIKE :like
           OR artworks.creator LIKE :like
           OR artworks.visual_structure_json LIKE :like
           OR artworks.design_language_json LIKE :like
           OR artworks.retrieval_json LIKE :like
           OR artworks.user_notes LIKE :like
           OR artworks.asset_type LIKE :like
        """
        params["like"] = f"%{query}%"

    order = {
        "oldest": "artworks.created_at ASC, artworks.id ASC",
        "popular": "json_extract(artworks.stats_json, '$.heartCount') DESC, json_extract(artworks.stats_json, '$.likeCount') DESC",
        "collected": "artworks.collected_at DESC",
    }.get(sort, "artworks.created_at DESC, artworks.id DESC")

    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            f"""
            SELECT artworks.* FROM artworks
            {join}
            {where}
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
            """,
            params,
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) AS total FROM artworks {join} {where}",
            {k: v for k, v in params.items() if k == "like"},
        ).fetchone()["total"]

    return {"items": [_deserialize(row) for row in rows], "total": total}


def get_artwork(artwork_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    init_db(db_path)
    with closing(_connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
    return _deserialize(row) if row else None


def export_creative_seeds(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for item in items:
        asset_type = item.get("asset_type") or "ai_generation_reference"
        base = {
            "id": f"seed_{item['id']}",
            "seed_type": asset_type,
            "source_artwork_id": item["id"],
            "source_url": item.get("source_url", ""),
            "image_path": item.get("preview_path", ""),
            "retrieval": item.get("retrieval", {}),
            "user_notes": item.get("user_notes", ""),
        }
        if asset_type == "graphic_design_reference":
            seeds.append(
                {
                    **base,
                    "generation_layer": {
                        "prompt": item.get("positive_prompt", ""),
                        "negative": item.get("negative_prompt", ""),
                        "visual_structure": item.get("visual_structure", {}),
                        "use_for": item.get("transfer", {}).get("use_for_generation", []),
                    },
                    "design_layer": {
                        "design_language": item.get("design_language", {}),
                        "use_for": item.get("transfer", {}).get("use_for_postprocess", []),
                        "requires_design_stage": bool(item.get("transfer", {}).get("requires_design_stage", True)),
                    },
                    "do_not_generate": item.get("transfer", {}).get("do_not_generate", []),
                }
            )
        elif asset_type == "photo_reference":
            seeds.append(
                {
                    **base,
                    "reference_layer": {
                        "visual_structure": item.get("visual_structure", {}),
                        "use_for": item.get("transfer", {}).get("use_for_generation", []),
                        "reference_mode": item.get("aigc_seed", {}).get("reference_mode", "composition_reference"),
                    },
                    "positive": {
                        "prompt": item.get("positive_prompt", ""),
                        "tags": item.get("raw_tags", []),
                    },
                    "negative": {"prompt": item.get("negative_prompt", "")},
                    "do_not_generate": item.get("transfer", {}).get("do_not_generate", []),
                }
            )
        else:
            seeds.append(
                {
                    **base,
                    "positive": {
                        "prompt": item.get("positive_prompt", ""),
                        "tags": item.get("raw_tags", []),
                    },
                    "negative": {"prompt": item.get("negative_prompt", "")},
                    "models": item.get("model_refs", []),
                    "stats": item.get("stats", {}),
                    "meta": _seed_meta(item.get("meta", {})),
                }
            )
    return seeds


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _serialize(artwork: dict[str, Any]) -> dict[str, Any]:
    return {
        **artwork,
        "asset_type": artwork.get("asset_type") or "ai_generation_reference",
        "raw_tags_json": json.dumps(artwork.get("raw_tags", []), ensure_ascii=False),
        "model_refs_json": json.dumps(artwork.get("model_refs", []), ensure_ascii=False),
        "stats_json": json.dumps(artwork.get("stats", {}), ensure_ascii=False),
        "meta_json": json.dumps(artwork.get("meta", {}), ensure_ascii=False),
        "visual_structure_json": json.dumps(artwork.get("visual_structure", {}), ensure_ascii=False),
        "design_language_json": json.dumps(artwork.get("design_language", {}), ensure_ascii=False),
        "transfer_json": json.dumps(artwork.get("transfer", {}), ensure_ascii=False),
        "aigc_seed_json": json.dumps(artwork.get("aigc_seed", {}), ensure_ascii=False),
        "retrieval_json": json.dumps(artwork.get("retrieval", {}), ensure_ascii=False),
        "user_notes": artwork.get("user_notes", ""),
    }


def _deserialize(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["raw_tags"] = _loads(item.pop("raw_tags_json"), [])
    item["model_refs"] = _loads(item.pop("model_refs_json"), [])
    item["stats"] = _loads(item.pop("stats_json"), {})
    item["meta"] = _loads(item.pop("meta_json"), {})
    item["visual_structure"] = _loads(item.pop("visual_structure_json", "{}"), {})
    item["design_language"] = _loads(item.pop("design_language_json", "{}"), {})
    item["transfer"] = _loads(item.pop("transfer_json", "{}"), {})
    item["aigc_seed"] = _loads(item.pop("aigc_seed_json", "{}"), {})
    item["retrieval"] = _loads(item.pop("retrieval_json", "{}"), {})
    return item


def _replace_fts(conn: sqlite3.Connection, artwork: dict[str, Any]) -> None:
    conn.execute("DELETE FROM artworks_fts WHERE id = ?", (artwork["id"],))
    conn.execute(
        """
        INSERT INTO artworks_fts (id, positive_prompt, negative_prompt, raw_tags, creator, model_refs)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            artwork["id"],
            artwork.get("positive_prompt", ""),
            artwork.get("negative_prompt", ""),
            " ".join(artwork.get("raw_tags", [])) + " " + _search_json_text(artwork),
            artwork.get("creator", ""),
            json.dumps(artwork.get("model_refs", []), ensure_ascii=False),
        ),
    )


def _ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(artworks)").fetchall()}
    specs = {
        "asset_type": "TEXT NOT NULL DEFAULT 'ai_generation_reference'",
        "visual_structure_json": "TEXT NOT NULL DEFAULT '{}'",
        "design_language_json": "TEXT NOT NULL DEFAULT '{}'",
        "transfer_json": "TEXT NOT NULL DEFAULT '{}'",
        "aigc_seed_json": "TEXT NOT NULL DEFAULT '{}'",
        "retrieval_json": "TEXT NOT NULL DEFAULT '{}'",
        "user_notes": "TEXT DEFAULT ''",
    }
    for name, spec in specs.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE artworks ADD COLUMN {name} {spec}")


def _search_json_text(artwork: dict[str, Any]) -> str:
    parts = [
        artwork.get("asset_type", ""),
        artwork.get("user_notes", ""),
        json.dumps(artwork.get("visual_structure", {}), ensure_ascii=False),
        json.dumps(artwork.get("design_language", {}), ensure_ascii=False),
        json.dumps(artwork.get("transfer", {}), ensure_ascii=False),
        json.dumps(artwork.get("retrieval", {}), ensure_ascii=False),
    ]
    return " ".join(str(part) for part in parts if part)


def _fts_query(value: str) -> str:
    terms = [term.replace('"', "") for term in value.split() if term.strip()]
    return " OR ".join(f'"{term}"' for term in terms) or '""'


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _seed_meta(meta: dict[str, Any]) -> dict[str, Any]:
    keys = ("seed", "sampler", "steps", "cfgScale", "Size", "Model", "model")
    return {key: meta[key] for key in keys if key in meta}
