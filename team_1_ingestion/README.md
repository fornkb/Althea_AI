# Althea AI — Person 1

Installable audio/transcript ingestion and SQLite storage. No other team package is imported. The offline sample is a fictional transcript with no recorded audio.

## Setup (PowerShell, from this folder)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m althea_ingestion --mode fixture --sample riverton_demo --output out/transcript.json
python -m althea_ingestion --mode fixture --input fixtures/transcript.json --output out/imported.json
```

Without installation, use `$env:PYTHONPATH='src'` with a Python 3.12 environment containing Pydantic 2, pytest and google-genai. Tests need no credentials, audio binaries or network. If a restricted environment cannot create temporary files, create `.tmp` and set `TEMP` and `TMP` to its absolute path before testing.

## Live transcription

Install FFmpeg from a trusted Windows distribution linked by [FFmpeg](https://ffmpeg.org/download.html), extract it, and add its `bin` directory to PATH. Both `ffmpeg -version` and `ffprobe -version` must work in a new PowerShell window. This package does not install system tools.

Enable the appropriate Google Cloud service and model in a project with billing, and configure [Application Default Credentials](https://cloud.google.com/docs/authentication/provide-credentials-adc). For a local developer session, `gcloud auth application-default login` is the usual command. Confirm project permissions, model availability, location and credit eligibility with your account; there is no automatic billing-route switch.

```powershell
$env:GOOGLE_CLOUD_PROJECT='your-project-id'
$env:GOOGLE_CLOUD_LOCATION='global'
$env:ALTHEA_TRANSCRIBE_MODEL='gemini-3.5-transcribe'
python -m althea_ingestion --mode live --input 'C:\clips\authorized debate.wav' --output out/live-transcript.json
```

Audio is sent to the configured hosted service. Use an authorized clip. JSON import makes zero external calls, including in live mode. The five-minute and 20 MiB caps apply before any cloud request. Imports with an inconsistent ID are rejected with the expected ID. Fixture provenance is preserved on import; API-origin transcripts become imported.

The adapter requests VERBATIM, English, diarization and word timestamps through the current SDK's `AudioTranscriptionConfig`. Missing timing/speaker annotations are errors. Speaker IDs denote attribution, not real identity. Word annotations are grouped at speaker changes or gaps greater than one second; overlap remains. Individual word spellings are preserved and spaces join adjacent words. Attribution above two speakers needs review. Digitally silent audio is rejected; near-silence and transcription accuracy require human review.

The original bytes are stored under `data_dir/media/<sha256>/original.<ext>`. MP3 and 16-bit PCM WAV are passed through; other WAV encodings are converted to 16-bit PCM with all channels retained. One to eight audio channels are accepted. The silence check decodes at 16 kHz without downmixing. Stereo channels are never blindly mixed. The hash always describes the original upload. Original filenames are metadata only.

## Public interface

```python
from althea_ingestion import IngestionService, Repository, validate_transcript, recompute_transcript_id

settings = {'mode': 'fixture', 'data_dir': r'C:\althea\data'}
class NoCalls:
    def consume(self, stage):
        raise AssertionError('No provider requests expected')

t = IngestionService(settings).ingest(
    {'kind': 'sample', 'local_path': None, 'sample_id': 'riverton_demo', 'title': 'Sample'},
    budget=NoCalls())
repo = Repository(r'C:\althea\data\jobs.sqlite')  # parent must already exist
repo.initialize()
```

`Repository` exports the entire frozen API: `save_snapshot`, `load_snapshot`, `list_jobs`, `get_cached`, `put_cached`, `consume_attempt`, `attempts_used`, `reserve_verification_pairs`, `append_event`, `review_transcript`. Methods exchange dictionaries. Initialization is explicit. Transactions preserve immutable artifact versions and database-owned counters. Artifact IDs hash the entire payload; semantic IDs exclude execution metadata. Attempts cap at 20, distinct pairs at four; request tokens are `analysis_id:pair_id`. Saving a snapshot or correcting a transcript never resets these counters.

Cache keys belong to final integration and must include stage/schema/input/model/location/prompt/settings/mode. Cache stores artifact dictionaries, not arbitrary objects or failures. Verification cache entries require upstream semantic validation by the caller because the cache API has no Analysis argument. Loading/saving snapshots validates the full chain. Cache reads are fresh objects. Events accept the Issue shape, redact common credential assignments, and must receive safe diagnostic messages rather than raw provider payloads or audio.

`review_transcript` accepts a full copy of the old transcript. Change only names and existing segment text/speaker/timing. It recomputes the identity, marks human review and clears downstream artifacts in one transaction. No-op reviews leave the snapshot unchanged. Reanalysis is a separate integration action.

Injected `transcriber.transcribe(path, *, language, expected_speakers, budget, progress=None)` returns `{'words': [{'word': str, 'speaker': opaque_id, 'start_s': seconds, 'end_s': seconds}], 'usage': [Usage, ...]}`. It owns all attempt reservations. `FixtureTranscriber` is a test fake, never an automatic audio fallback. Sample ingestion reads the saved transcript directly. Live calls reserve immediately before attempts, disable SDK retries and retry only transient failures, at most three attempts. No repair requests are made.

See the [root README](../README.md) for the current integrated setup, validation status and limitations. Current official API references: [transcription](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-transcribe), [SDK](https://github.com/googleapis/python-genai).
