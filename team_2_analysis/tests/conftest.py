import copy
import json
from pathlib import Path
import pytest
from althea_analysis.utils import digest, transcript_identity

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def transcript():
    return json.loads((ROOT / "fixtures/transcript.json").read_text(encoding="utf-8"))


@pytest.fixture
def expected():
    return json.loads((ROOT / "fixtures/expected_analysis.json").read_text(encoding="utf-8"))


def make_transcript(texts, *, speakers=None):
    speakers = speakers or ["speaker_01" if i % 2 == 0 else "speaker_02" for i in range(len(texts))]
    segments = [dict(segment_id=f"seg_{i:04d}", speaker_id=speaker,
                     start_s=float(i - 1), end_s=float(i), text=text)
                for i, (text, speaker) in enumerate(zip(texts, speakers), 1)]
    t = dict(schema_version="1.0.0", transcript_id="pending", origin="fixture", language="en",
             duration_s=float(max(1, len(texts))),
             source=dict(kind="sample", title="Synthetic test", original_filename=None,
                         content_sha256=digest(segments), audio_relpath=None),
             speakers=[dict(speaker_id=s, display_name=s) for s in sorted(set(speakers))],
             segments=segments, issues=[], usage=[])
    t["transcript_id"] = transcript_identity(t)
    return t


def proposal(transcript, index, *, quantity_raw=None, **overrides):
    segment = transcript["segments"][index]
    c = dict(speaker_id=segment["speaker_id"], proposition=segment["text"], subject="Riverton",
             metric="facility status", period="2024", geography="Riverton", population="not_applicable",
             measurement_basis="status in calendar year", qualifiers=[], checkability="checkable",
             missing_context=[], source_spans=[dict(segment_id=segment["segment_id"], quote=segment["text"],
                                                   start_char=None, end_char=None)],
             quantity_raw=quantity_raw, currency_context=None)
    c.update(copy.deepcopy(overrides))
    return c
