"""Versioned JSON artifacts with SQLite-owned atomic resource counters."""
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .common import canonical, digest, now, validate_snapshot, validate_transcript, validate_analysis, reviewed_transcript
from ._contract import Verification, Issue
from .common import wire, verification_identity
from .errors import ComponentError, require


class Repository:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)

    @contextmanager
    def _transaction(self):
        connection = None
        try:
            connection = sqlite3.connect(self.db_path, timeout=15)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            if connection:
                connection.rollback()
            raise ComponentError('STORAGE_ERROR', 'Local storage operation failed; check database path, permissions and available space.', stage='storage') from exc
        except Exception:
            if connection:
                connection.rollback()
            raise
        finally:
            if connection:
                connection.close()

    def initialize(self) -> None:
        with self._transaction() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            require(version in (0, 1), 'Unsupported database schema.')
            statements = [
                'CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,title TEXT NOT NULL,mode TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,snapshot_json TEXT NOT NULL,attempts_used INTEGER NOT NULL DEFAULT 0)',
                'CREATE TABLE IF NOT EXISTS artifacts(artifact_id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS job_artifacts(job_id TEXT NOT NULL REFERENCES jobs(job_id),artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),PRIMARY KEY(job_id,artifact_id))',
                'CREATE TABLE IF NOT EXISTS cache(cache_key TEXT PRIMARY KEY,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS verified_pairs(job_id TEXT NOT NULL REFERENCES jobs(job_id),pair_id TEXT NOT NULL,PRIMARY KEY(job_id,pair_id))',
                'CREATE TABLE IF NOT EXISTS events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES jobs(job_id),created_at TEXT NOT NULL,event_json TEXT NOT NULL)']
            for sql in statements:
                db.execute(sql)
            db.execute('PRAGMA user_version=1')

    def _save(self, db, s):
        existing = db.execute('SELECT created_at,mode FROM jobs WHERE job_id=?',(s['job_id'],)).fetchone()
        require(existing is None or (existing['created_at']==s['created_at'] and existing['mode']==s['mode']), 'Existing job creation time and mode are immutable.')
        db.execute('''INSERT INTO jobs(job_id,title,mode,status,created_at,updated_at,snapshot_json)
                      VALUES(?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET
                      title=excluded.title,mode=excluded.mode,status=excluded.status,
                      updated_at=excluded.updated_at,snapshot_json=excluded.snapshot_json''',
                   tuple(s[k] for k in ('job_id','title','mode','status','created_at','updated_at')) + (canonical(s).decode(),))
        for kind in ('transcript', 'analysis', 'verification'):
            payload = s[kind]
            if payload is None:
                continue
            content = canonical(payload).decode()
            artifact_id = kind + ':' + digest(payload)
            old = db.execute('SELECT payload_json,kind FROM artifacts WHERE artifact_id=?', (artifact_id,)).fetchone()
            require(old is None or (old['payload_json'] == content and old['kind'] == kind), 'Immutable artifact collision.')
            db.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?)', (artifact_id,kind,content,now()))
            db.execute('INSERT OR IGNORE INTO job_artifacts VALUES(?,?)', (s['job_id'],artifact_id))

    def save_snapshot(self, snapshot: dict) -> None:
        s = validate_snapshot(snapshot)
        with self._transaction() as db:
            self._save(db, s)

    def _load(self, db, job_id):
        row = db.execute('SELECT snapshot_json FROM jobs WHERE job_id=?', (job_id,)).fetchone()
        require(row is not None, 'Saved job does not exist.', 'JOB_NOT_FOUND')
        return validate_snapshot(json.loads(row[0]))

    def load_snapshot(self, job_id: str) -> dict:
        with self._transaction() as db:
            return self._load(db, job_id)

    def list_jobs(self, limit: int = 20) -> list[dict]:
        require(isinstance(limit, int) and 0 <= limit <= 1000, 'Invalid history limit.')
        with self._transaction() as db:
            return [dict(row) for row in db.execute('SELECT job_id,title,mode,status,updated_at FROM jobs ORDER BY updated_at DESC,job_id LIMIT ?', (limit,))]

    def _cache_artifact(self, payload):
        if 'transcript_id' in payload and 'segments' in payload:
            return validate_transcript(payload)
        if 'analysis_id' in payload and 'claims' in payload:
            return validate_analysis(payload)
        if 'verification_id' in payload:
            v = wire(Verification, payload)
            require(v['verification_id'] == verification_identity(v), 'Invalid verification cache identity.')
            require(not any(u['reason'] in ('provider_error','budget_limit') for u in v['unverified']), 'Failed verification pairs must not be cached as successful results.')
            # Cross-artifact validation is performed by the backend before caching.
            return v
        if 'job_id' in payload:
            s = validate_snapshot(payload)
            require(s['status'] in ('ready','complete'), 'Failed, partial or running jobs cannot be cached as successful results.')
            return s
        raise ComponentError('CONTRACT_INVALID', 'Cache accepts validated artifact dictionaries only.')

    def get_cached(self, cache_key: str) -> dict | None:
        with self._transaction() as db:
            row = db.execute('SELECT payload_json FROM cache WHERE cache_key=?', (cache_key,)).fetchone()
            return self._cache_artifact(json.loads(row[0])) if row else None

    def put_cached(self, cache_key: str, payload: dict) -> None:
        value = self._cache_artifact(payload)
        with self._transaction() as db:
            db.execute('INSERT INTO cache VALUES(?,?,?) ON CONFLICT(cache_key) DO UPDATE SET payload_json=excluded.payload_json,created_at=excluded.created_at', (cache_key, canonical(value).decode(), now()))

    def consume_attempt(self, job_id: str, stage: str, limit: int) -> None:
        require(stage in ('transcription','extraction','comparison','retrieval','adjudication') and isinstance(limit, int) and 0 <= limit <= 20, 'Invalid provider budget.')
        with self._transaction() as db:
            row = db.execute('SELECT attempts_used FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            require(row is not None, 'Unknown job.', 'JOB_NOT_FOUND')
            require(row[0] < limit, 'The provider-attempt budget is exhausted.', 'BUDGET_LIMIT')
            db.execute('UPDATE jobs SET attempts_used=attempts_used+1 WHERE job_id=?', (job_id,))

    def attempts_used(self, job_id: str) -> int:
        with self._transaction() as db:
            row = db.execute('SELECT attempts_used FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            require(row is not None, 'Unknown job.', 'JOB_NOT_FOUND')
            return row[0]

    def reserve_verification_pairs(self, job_id: str, pair_ids: list[str], limit: int) -> list[str]:
        require(isinstance(limit, int) and 0 <= limit <= 4 and all(isinstance(p, str) and ':' in p for p in pair_ids), 'Expected analysis-qualified pair reservations and cap <=4.')
        with self._transaction() as db:
            require(db.execute('SELECT 1 FROM jobs WHERE job_id=?', (job_id,)).fetchone() is not None, 'Unknown job.', 'JOB_NOT_FOUND')
            used = {r[0] for r in db.execute('SELECT pair_id FROM verified_pairs WHERE job_id=?', (job_id,))}
            allowed = []
            for token in pair_ids:
                if token in used or len(used) < limit:
                    db.execute('INSERT OR IGNORE INTO verified_pairs VALUES(?,?)', (job_id, token))
                    used.add(token)
                    allowed.append(token)
            return allowed

    def append_event(self, job_id: str, event: dict) -> None:
        safe = wire(Issue, event)
        # Persist codes/references and a redacted diagnostic, never provider response bodies.
        safe['message'] = re.sub(r'(?i)(bearer\s+\S+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+)', '[redacted]', safe['message'])[:1000]
        with self._transaction() as db:
            db.execute('INSERT INTO events(job_id,created_at,event_json) VALUES(?,?,?)', (job_id, now(), canonical(safe).decode()))

    def review_transcript(self, job_id: str, reviewed: dict) -> dict:
        with self._transaction() as db:
            s = self._load(db, job_id)
            require(s['transcript'] is not None, 'No transcript to review.')
            t = reviewed_transcript(s['transcript'], reviewed)
            if t['transcript_id'] == s['transcript']['transcript_id']:
                return s
            s.update(transcript=t, analysis=None, verification=None, status='ready', updated_at=now())
            self._save(db, s)
            return s

    def delete_cached(self, cache_key: str) -> None:
        """Explicit refresh removes a key without touching historical artifacts."""
        with self._transaction() as db:
            db.execute('DELETE FROM cache WHERE cache_key=?',(cache_key,))

    def job_metrics(self, job_id: str) -> dict:
        with self._transaction() as db:
            row=db.execute('SELECT attempts_used FROM jobs WHERE job_id=?',(job_id,)).fetchone()
            require(row is not None,'Unknown job.','JOB_NOT_FOUND')
            pairs=db.execute('SELECT COUNT(*) FROM verified_pairs WHERE job_id=?',(job_id,)).fetchone()[0]
            return dict(attempts_used=row[0],verification_pairs_used=pairs)

    def running_jobs(self) -> list[dict]:
        with self._transaction() as db:
            return [dict(row) for row in db.execute("SELECT job_id,title,mode,status,updated_at FROM jobs WHERE status='running'")]

    def events_for_job(self, job_id: str) -> list[dict]:
        with self._transaction() as db:
            return [dict(created_at=r['created_at'],event=json.loads(r['event_json'])) for r in db.execute('SELECT created_at,event_json FROM events WHERE job_id=? ORDER BY event_id',(job_id,))]

    def native_attribution_hashes(self) -> set[str]:
        # Only integration writes this code after observing native provider metadata.
        with self._transaction() as db:
            result=set()
            for row in db.execute('SELECT event_json FROM events'):
                event=json.loads(row[0])
                if event.get('code')=='NATIVE_GROUNDING' and event.get('related_ids'):
                    result.add(event['related_ids'][0])
            return result

    def artifact_history(self, job_id: str) -> list[dict]:
        with self._transaction() as db:
            return [dict(artifact_id=r['artifact_id'],kind=r['kind'],created_at=r['created_at'],payload=json.loads(r['payload_json'])) for r in db.execute('SELECT a.* FROM artifacts a JOIN job_artifacts j ON a.artifact_id=j.artifact_id WHERE j.job_id=? ORDER BY a.created_at,a.artifact_id',(job_id,))]
