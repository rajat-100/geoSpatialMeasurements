"""
Lightweight SQLite persistence layer.
Stores file metadata, processing results, and feature measurements.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("GSPACE_DB_PATH", "geospatial_api.db")


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Create the files table if it doesn't exist."""
    with _connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id              TEXT PRIMARY KEY,
                filename        TEXT    NOT NULL,
                feature_count   INTEGER NOT NULL,
                crs             TEXT    NOT NULL,
                projected_crs   TEXT,
                status          TEXT    NOT NULL DEFAULT 'COMPLETED',
                created_at      TEXT    NOT NULL,
                summary_json    TEXT,
                features_json   TEXT
            )
        """)
        conn.commit()


def save_processed_file(
    filename: str,
    feature_count: int,
    crs: str,
    projected_crs: str,
    features: List[Dict[str, Any]],
    summary: Dict[str, Any],
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    """Persist a fully-processed geospatial file and return its metadata."""
    init_db(db_path)
    file_id = uuid.uuid4().hex[:8]
    now_iso = datetime.now(timezone.utc).isoformat()

    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO files
                (id, filename, feature_count, crs, projected_crs,
                 status, created_at, summary_json, features_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id, filename, feature_count, crs, projected_crs,
                "COMPLETED", now_iso,
                json.dumps(summary), json.dumps(features),
            ),
        )
        conn.commit()

    return {
        "id": file_id,
        "filename": filename,
        "feature_count": feature_count,
        "crs": crs,
        "projected_crs": projected_crs,
        "status": "COMPLETED",
        "created_at": now_iso,
    }


def get_file_by_id(file_id: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieve file metadata + summary (without the heavy features payload)."""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, filename, feature_count, crs, projected_crs,
                   status, created_at, summary_json
            FROM files WHERE id = ?
            """,
            (file_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "filename": row["filename"],
        "feature_count": row["feature_count"],
        "crs": row["crs"],
        "projected_crs": row["projected_crs"],
        "status": row["status"],
        "created_at": row["created_at"],
        "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
    }


def get_file_measurements(
    file_id: str, db_path: str = DB_PATH
) -> Optional[Dict[str, Any]]:
    """Retrieve full measurements (features + summary) for a file."""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, filename, feature_count, crs, projected_crs,
                   summary_json, features_json
            FROM files WHERE id = ?
            """,
            (file_id,),
        ).fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "filename": row["filename"],
        "feature_count": row["feature_count"],
        "crs": row["crs"],
        "projected_crs": row["projected_crs"],
        "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
        "features": json.loads(row["features_json"]) if row["features_json"] else [],
    }


def list_files(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Return all uploaded files ordered newest-first."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, filename, feature_count, crs, projected_crs,
                   status, created_at
            FROM files ORDER BY created_at DESC
            """
        ).fetchall()

    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "feature_count": r["feature_count"],
            "crs": r["crs"],
            "projected_crs": r["projected_crs"],
            "status": r["status"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
