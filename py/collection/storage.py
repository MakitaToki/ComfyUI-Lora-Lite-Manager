from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..config import PLUGIN_ROOT


COLLECTION_DIR = PLUGIN_ROOT / "data" / "collection"
DB_PATH = COLLECTION_DIR / "collection.sqlite3"


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artworks (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
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


def upsert_artwork(artwork: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO artworks (
                id, source, source_id, source_url, image_url, preview_path,
                width, height, nsfw, nsfw_level, creator,
                positive_prompt, negative_prompt, raw_tags_json, model_refs_json,
                stats_json, meta_json, created_at, collected_at, updated_at
            )
            VALUES (
                :id, :source, :source_id, :source_url, :image_url, :preview_path,
                :width, :height, :nsfw, :nsfw_level, :creator,
                :positive_prompt, :negative_prompt, :raw_tags_json, :model_refs_json,
                :stats_json, :meta_json, :created_at, :collected_at, CURRENT_TIMESTAMP
            )
            ON CONFLICT(id) DO UPDATE SET
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
        join = "JOIN artworks_fts ON artworks_fts.id = artworks.id"
        where = "WHERE artworks_fts MATCH :query"
        params["query"] = _fts_query(query)

    order = {
        "oldest": "artworks.created_at ASC, artworks.id ASC",
        "popular": "json_extract(artworks.stats_json, '$.heartCount') DESC, json_extract(artworks.stats_json, '$.likeCount') DESC",
        "collected": "artworks.collected_at DESC",
    }.get(sort, "artworks.created_at DESC, artworks.id DESC")

    with _connect(db_path) as conn:
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
            {k: v for k, v in params.items() if k == "query"},
        ).fetchone()["total"]

    return {"items": [_deserialize(row) for row in rows], "total": total}


def get_artwork(artwork_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
    return _deserialize(row) if row else None


def export_creative_seeds(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    for item in items:
        seeds.append(
            {
                "id": f"seed_{item['id']}",
                "source_artwork_id": item["id"],
                "source_url": item.get("source_url", ""),
                "image_path": item.get("preview_path", ""),
                "positive": {
                    "prompt": item.get("positive_prompt", ""),
                    "tags": item.get("raw_tags", []),
                },
                "negative": {
                    "prompt": item.get("negative_prompt", ""),
                },
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
        "raw_tags_json": json.dumps(artwork.get("raw_tags", []), ensure_ascii=False),
        "model_refs_json": json.dumps(artwork.get("model_refs", []), ensure_ascii=False),
        "stats_json": json.dumps(artwork.get("stats", {}), ensure_ascii=False),
        "meta_json": json.dumps(artwork.get("meta", {}), ensure_ascii=False),
    }


def _deserialize(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["raw_tags"] = _loads(item.pop("raw_tags_json"), [])
    item["model_refs"] = _loads(item.pop("model_refs_json"), [])
    item["stats"] = _loads(item.pop("stats_json"), {})
    item["meta"] = _loads(item.pop("meta_json"), {})
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
            " ".join(artwork.get("raw_tags", [])),
            artwork.get("creator", ""),
            json.dumps(artwork.get("model_refs", []), ensure_ascii=False),
        ),
    )


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
