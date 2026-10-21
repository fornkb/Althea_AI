import json
import os
import sqlite3
import hashlib
import datetime
from typing import Any, List, Optional

# Stub implementations for service functions required by Repository.
# In the real system these will be provided by the ingestion side.

def validate_transcript(payload: dict) -> dict:
    """Placeholder validation – simply returns the payload unchanged."""
    return payload


def recompute_transcript_id(payload: dict) -> str:
    """Deterministic stub: compute ID based on content hash.

    This mirrors the contract's ID generation logic for testing purposes.
    """
    # Simplified: hash the JSON representation of the payload (excluding the ID itself).
    payload_copy = dict(payload)
    payload_copy.pop("transcript_id", None)
    canonical = json.dumps(payload_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "tr_" + hashlib.sha256(canonical).hexdigest()

# Export names expected by Repository.
__all__ = ["validate_transcript", "recompute_transcript_id"]
