import hashlib
import json


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(payload):
    return hashlib.sha256(canonical(payload)).hexdigest()


def transcript_identity(transcript):
    return "tr_" + digest({"content_sha256": transcript["source"]["content_sha256"],
                           **{k: transcript[k] for k in
                              ("language", "duration_s", "speakers", "segments")}})


def analysis_identity(analysis):
    return "an_" + digest({k: analysis[k] for k in ("transcript_id", "claims", "pairs")})


def issue(code, message, related_ids=None):
    return dict(stage="analysis", code=code, message=message,
                retryable=False, related_ids=related_ids or [])


def normalized(text):
    return " ".join((text or "").casefold().split())
