import json
import os
import sqlite3
import hashlib
import datetime
from typing import Any, List, Optional

from .errors import (
    StorageError,
    BUDGET_LIMIT,
    NOT_FOUND,
    STORAGE_ERROR,
    CONTRACT_INVALID,
)
from ._contract import Snapshot, JobSummary


def _now_iso() -> str:
    """Return current UTC time in ISO‑8601 format with ``Z`` suffix."""
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _canonical_json(payload: Any) -> bytes:
    """Return the canonical JSON representation used for artifact IDs.

    The specification requires ``sort_keys=True`` and compact separators.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _artifact_id(kind: str, payload: Any) -> str:
    """Compute ``artifact_id`` as ``"{kind}:{sha256}"``.

    ``payload`` is the full JSON payload that will be stored for the artifact.
    """
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    return f"{kind}:{digest}"


class Repository:
    """SQLite‑backed storage for Althea ingestion snapshots.

    The class does **not** create a database on import – callers must invoke
    :meth:`initialize` explicitly. All public methods raise :class:`StorageError`
    (or a subclass constant) on failure and never expose raw SQLite messages.
    """

    def __init__(self, db_path: str):
        self._db_path = os.path.abspath(db_path)
        # Connection is created on‑demand; we keep the path only.

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self._db_path, detect_types=sqlite3.PARSE_DECLTYPES)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        except sqlite3.Error as exc:
            raise StorageError(
                STORAGE_ERROR, retryable=False, stage="storage", message="Database connection failed"
            ) from exc

    def _execute(self, conn: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        try:
            cur = conn.execute(sql, params)
            return cur
        except sqlite3.Error as exc:
            raise StorageError(
                STORAGE_ERROR, retryable=False, stage="storage", message="Database operation failed"
            ) from exc

    # ---------------------------------------------------------------------
    # Schema management
    # ---------------------------------------------------------------------
    def initialize(self) -> None:
        """Create tables if they do not exist. Idempotent.

        ``PRAGMA user_version`` is set to ``1`` as required by the spec.
        """
        conn = self._connect()
        try:
            conn.execute("PRAGMA user_version=1")
            # jobs table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    attempts_used INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            # artifacts table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            # job_artifacts linking table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS job_artifacts (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
                    PRIMARY KEY (job_id, artifact_id)
                )
                """
            )
            # cache table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    cache_key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            # verified_pairs table – stores distinct pair identifiers per job
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verified_pairs (
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    pair_id TEXT NOT NULL,
                    PRIMARY KEY (job_id, pair_id)
                )
                """
            )
            # events table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    created_at TEXT NOT NULL,
                    event_json TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------------
    # Snapshot persistence
    # ---------------------------------------------------------------------
    def save_snapshot(self, snapshot: dict) -> None:
        """Validate and up‑sert a complete job snapshot.

        The caller is expected to have validated ``snapshot`` against the contract;
        this method focuses on persistence and atomicity.
        """
        required = {"job_id", "title", "mode", "status", "created_at", "updated_at", "schema_version"}
        if not required.issubset(snapshot):
            raise StorageError(CONTRACT_INVALID, retryable=False, stage="storage", message="Snapshot missing required fields")

        conn = self._connect()
        try:
            conn.isolation_level = None
            self._execute(conn, "BEGIN IMMEDIATE")
            cur = conn.execute("SELECT attempts_used FROM jobs WHERE job_id = ?", (snapshot["job_id"],))
            row = cur.fetchone()
            attempts_used = row["attempts_used"] if row else 0

            now = _now_iso()
            job_sql = """
                INSERT INTO jobs (job_id, title, mode, status, created_at, updated_at, snapshot_json, attempts_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    title=excluded.title,
                    mode=excluded.mode,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    snapshot_json=excluded.snapshot_json,
                    attempts_used=jobs.attempts_used
            """
            self._execute(
                conn,
                job_sql,
                (
                    snapshot["job_id"],
                    snapshot["title"],
                    snapshot["mode"],
                    snapshot["status"],
                    snapshot["created_at"],
                    now,
                    json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                    attempts_used,
                ),
            )

            def _store_artifact(kind: str, payload: dict) -> None:
                art_id = _artifact_id(kind, payload)
                cur = conn.execute("SELECT payload_json FROM artifacts WHERE artifact_id = ?", (art_id,))
                existing = cur.fetchone()
                payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                if existing:
                    if existing["payload_json"] != payload_json:
                        raise StorageError(
                            STORAGE_ERROR,
                            retryable=False,
                            stage="storage",
                            message="Artifact ID collision with different content",
                        )
                else:
                    conn.execute(
                        "INSERT INTO artifacts (artifact_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
                        (art_id, kind, payload_json, now),
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO job_artifacts (job_id, artifact_id) VALUES (?, ?)",
                    (snapshot["job_id"], art_id),
                )

            if snapshot.get("transcript"):
                _store_artifact("transcript", snapshot["transcript"])
            if snapshot.get("analysis"):
                _store_artifact("analysis", snapshot["analysis"])
            if snapshot.get("verification"):
                _store_artifact("verification", snapshot["verification"])

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_snapshot(self, job_id: str) -> dict:
        conn = self._connect()
        try:
            cur = conn.execute("SELECT snapshot_json FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise StorageError(NOT_FOUND, retryable=False, stage="storage", message="Job not found")
            return json.loads(row["snapshot_json"])
        finally:
            conn.close()

    def list_jobs(self, limit: int = 20) -> List[dict]:
        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT job_id, title, mode, status, updated_at FROM jobs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    # ---------------------------------------------------------------------
    # Cache handling
    # ---------------------------------------------------------------------
    def get_cached(self, cache_key: str) -> Optional[dict]:
        conn = self._connect()
        try:
            cur = conn.execute("SELECT payload_json FROM cache WHERE cache_key = ?", (cache_key,))
            row = cur.fetchone()
            if not row:
                return None
            try:
                payload = json.loads(row["payload_json"])
                return json.loads(json.dumps(payload))
            except json.JSONDecodeError:
                return None
        finally:
            conn.close()

    def put_cached(self, cache_key: str, payload: dict) -> None:
        conn = self._connect()
        try:
            now = _now_iso()
            payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                "INSERT OR REPLACE INTO cache (cache_key, payload_json, created_at) VALUES (?, ?, ?)",
                (cache_key, payload_json, now),
            )
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------------
    # Counters (attempts & verification pairs)
    # ---------------------------------------------------------------------
    def consume_attempt(self, job_id: str, stage: str, limit: int) -> None:
        conn = self._connect()
        try:
            conn.isolation_level = None
            self._execute(conn, "BEGIN IMMEDIATE")
            cur = conn.execute("SELECT attempts_used FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise StorageError(NOT_FOUND, retryable=False, stage="storage", message="Job not found")
            used = row["attempts_used"]
            if used >= limit:
                raise StorageError(BUDGET_LIMIT, retryable=False, stage=stage, message="Attempt budget exceeded")
            conn.execute("UPDATE jobs SET attempts_used = attempts_used + 1 WHERE job_id = ?", (job_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def attempts_used(self, job_id: str) -> int:
        conn = self._connect()
        try:
            cur = conn.execute("SELECT attempts_used FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise StorageError(NOT_FOUND, retryable=False, stage="storage", message="Job not found")
            return row["attempts_used"]
        finally:
            conn.close()

    def reserve_verification_pairs(self, job_id: str, pair_ids: List[str], limit: int) -> List[str]:
        """Reserve distinct verification pair tokens up to ``limit``.

        Already‑reserved tokens are returned without consuming a new slot.
        """
        conn = self._connect()
        try:
            conn.isolation_level = None
            self._execute(conn, "BEGIN IMMEDIATE")
            cur = conn.execute("SELECT pair_id FROM verified_pairs WHERE job_id = ?", (job_id,))
            existing = {row["pair_id"] for row in cur.fetchall()}
            allowed: List[str] = []
            distinct = len(existing)
            for pid in pair_ids:
                if pid in existing:
                    allowed.append(pid)
                elif distinct < limit:
                    conn.execute(
                        "INSERT INTO verified_pairs (job_id, pair_id) VALUES (?, ?)",
                        (job_id, pid),
                    )
                    allowed.append(pid)
                    distinct += 1
                else:
                    break
            conn.commit()
            return allowed
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------------------------------------------------------------------
    # Event logging
    # ---------------------------------------------------------------------
    def append_event(self, job_id: str, event: dict) -> None:
        for v in event.values():
            if isinstance(v, (bytes, bytearray)):
                raise StorageError(CONTRACT_INVALID, retryable=False, stage="storage", message="Event contains binary data")
            if isinstance(v, str) and len(v) > 4096:
                raise StorageError(CONTRACT_INVALID, retryable=False, stage="storage", message="Event value too large")
        conn = self._connect()
        try:
            now = _now_iso()
            payload_json = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                "INSERT INTO events (job_id, created_at, event_json) VALUES (?, ?, ?)",
                (job_id, now, payload_json),
            )
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------------
    # Human transcript review
    # ---------------------------------------------------------------------
    def review_transcript(self, job_id: str, reviewed: dict) -> dict:
        """Replace the transcript artifact with a human‑reviewed version.

        Only mutable fields (speakers, segments) may be supplied in ``reviewed``.
        Immutable fields are verified to stay unchanged. A new artifact is stored,
        analysis/verification pointers are cleared, and the updated snapshot is
        returned.
        """
        snapshot = self.load_snapshot(job_id)
        original = snapshot.get("transcript")
        if not original:
            raise StorageError(CONTRACT_INVALID, retryable=False, stage="storage", message="No transcript to review")

        mutable_top_keys = {"speakers", "segments"}
        for key in reviewed:
            if key not in mutable_top_keys:
                raise StorageError(CONTRACT_INVALID, retryable=False, stage="storage", message=f"Field '{key}' may not be changed in review")

        new_transcript = {**original, **reviewed}
        immutable_fields = ["media_hash", "filename", "audio_path", "language", "duration_s", "schema_version", "source", "origin"]
        for f in immutable_fields:
            if new_transcript.get(f) != original.get(f):
                raise StorageError(CONTRACT_INVALID, retryable=False, stage="storage", message=f"Immutable field '{f}' changed")

        # Stub for recompute_transcript_id – will be provided by the ingestion side.
        try:
            from .service import recompute_transcript_id  # type: ignore
        except Exception as exc:
            raise NotImplementedError("recompute_transcript_id not available") from exc
        new_id = recompute_transcript_id(new_transcript)
        new_transcript["transcript_id"] = new_id
        new_transcript["origin"] = "human_reviewed"

        conn = self._connect()
        try:
            conn.isolation_level = None
            self._execute(conn, "BEGIN IMMEDIATE")
            now = _now_iso()
            # Store new transcript artifact.
            art_id = _artifact_id("transcript", new_transcript)
            payload_json = json.dumps(new_transcript, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                "INSERT INTO artifacts (artifact_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (art_id, "transcript", payload_json, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO job_artifacts (job_id, artifact_id) VALUES (?, ?)",
                (job_id, art_id),
            )
            # Update job row – keep counters untouched.
            snapshot["transcript"] = new_transcript
            snapshot["analysis"] = None
            snapshot["verification"] = None
            snapshot["status"] = "ready"
            snapshot["updated_at"] = now
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ?, snapshot_json = ? WHERE job_id = ?",
                (
                    "ready",
                    now,
                    json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                    job_id,
                ),
            )
            conn.commit()
            return snapshot
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---------------------------------------------------------------------
    # Test helper – not part of public API
    # ---------------------------------------------------------------------
    def _reset_db_for_tests(self) -> None:
        if os.path.exists(self._db_path):
            os.remove(self._db_path)
