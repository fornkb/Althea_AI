# Althea AI

A local application for reviewing spoken claims, comparing speakers and checking selected disagreements against retrieved evidence.

## Run

Requires Python 3.12. From the repository root in PowerShell:

```powershell
./setup.ps1
./run.ps1
```

Open the localhost address shown by Streamlit. The interface has two sections:

- **Home:** Upload audio, Record debate, or Try sample; review transcripts, claims, disagreements and evidence; export results.
- **Settings:** Select the analysis provider and configure your Gemini API key. Keys entered here stay in session memory and are excluded from saved jobs and exports.

Choose **Try sample** for a fictional two-speaker debate that works offline without credentials. Its eight turns produce seven claims, three assessed pairs and one eligible disagreement. Evidence is explicitly synthetic; both budget claims are refuted. There is no sample audio or live search implied.

## Audio and provider setup

**Gemini API:** In Settings, select Gemini API key, enter a key and choose Use API key. Return Home to record or upload. Free-tier eligibility, model availability and quotas depend on the key's project; the app does not change billing or automatically switch providers. Defaults use `gemini-2.5-flash`.

**Google Cloud:** Configure your existing project, model access and Application Default Credentials, then select Live analysis in Settings. The default native transcription model is `gemini-3.5-transcribe`; availability and annotations depend on account/model support.

Install both FFmpeg and ffprobe and add their executable directory to PATH before processing audio. Settings reports missing binaries. Use the distributions linked by [FFmpeg](https://ffmpeg.org/download.html). The sample and complete Transcript JSON import do not require these binaries.

Audio is English, MP3/WAV, up to five minutes. Gemini inline audio is limited to 13 MiB; the Cloud route allows 20 MiB. Record debate uses the browser microphone and 16 kHz WAV. Start/stop capture yourself, stop within five minutes and listen back before choosing Analyze. The recorder does not automatically stop at the duration limit; ingestion rejects overlong recordings. Recording, preview and page navigation do not start model requests.

Use recordings you are authorized to process. Analyze and evidence actions transmit audio/text to the selected provider. Gemini speaker turns/timings are model-generated and approximate; review playback, names, numbers and negation. Missing annotations are rejected rather than invented. Native Cloud annotations also need human review.

To import complete Transcript JSON, use Home → Upload audio → Import an existing transcript instead.

## Configuration

Only the application loads `.env`. Copy `.env.example` to `.env` if needed; environment variables take precedence. Never commit real keys or credential files.

| Variable | Purpose |
|---|---|
| `ALTHEA_PROVIDER` | `vertex` or `gemini` for CLI/configuration |
| `GEMINI_API_KEY` | Developer API key; UI entry is also available |
| `GOOGLE_CLOUD_PROJECT` | Existing Cloud project |
| `GOOGLE_CLOUD_LOCATION` | Model location; default `global` |
| `ALTHEA_TRANSCRIBE_MODEL` | Native Cloud transcription model |
| `ALTHEA_GEMINI_AUDIO_MODEL` | Gemini audio-understanding model |
| `ALTHEA_TEXT_MODEL` | Extraction/comparison/adjudication model |
| `ALTHEA_GROUNDING_MODEL` | Grounded retrieval model |
| `ALTHEA_DATA_DIR` | Local data directory; default `data` |

Key entry and ordinary preflight make no external request. CLI keys supplied through the environment or `.env` remain there until you remove them. The Settings Clear API key action removes the current session key only.

## Command line

Activate the environment first:

```powershell
.\.venv\Scripts\Activate.ps1
python -m althea_app --help
python -m althea_app --preflight
python -m althea_app --mode fixture --sample riverton_demo --verify --output data/sample.json
python -m althea_app --mode live --provider gemini --input 'C:\clips\debate.wav' --verify --output data/result.json
```

`--provider vertex` selects the Cloud route. `--title` and `--data-dir` are supported. A failed/partial run still exports usable upstream work and exits nonzero. `--live-smoke` explicitly makes at most one accounted text request; it does not establish audio, grounding or accuracy.

## Saved work and limits

Jobs and immutable artifact versions persist in SQLite. Sample, Gemini and Cloud use separate databases/cache namespaces. Source audio is stored beneath `data/media`; uploaded filenames never become filesystem targets. Runtime data is ignored by Git. Stop the app before backing up `data/`.

Saving a transcript/speaker correction creates a new identity and clears active claims/evidence atomically. Reanalysis is explicit and avoids retranscription. Old artifacts remain downloadable. Arbitrary edits to the fictional sample require live analysis rather than manufactured replacement claims.

Each job has a persisted cap of 20 provider attempts, including retries/failures, and four distinct analysis-qualified evidence pairs. A call cap is not a currency spending guarantee. Exact-content cache reuse adds no new requests; provider, model, schema, prompt and version changes invalidate relevant caches. Evidence remains dated until explicitly refreshed.

Incremental checks preserve other pairs. Failed refresh removes the selected active verdict while retaining history. Job locks and transactional counters protect concurrent actions. Interrupted jobs are marked partial/failed on startup without automatically resuming provider calls.

Evidence retrieval and adjudication are separate requests. Native metadata supplies source links. A grounded AI summary is labelled accordingly, not presented as a website quotation. Claims are assessed independently; the app does not select a debate winner or produce a confidence percentage. CSV exports escape formula-leading textual cells; JSON retains original content.

## Development and tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pytest
python -m streamlit run integration/app.py
```

The latest offline regression run passed **246 tests**, with five live tests deselected. Offline tests block network access and use temporary storage/provider simulations. Explicit live tests require their individual opt-in environment variables. No real key, authorized recording or human-labelled accuracy evaluation has been supplied; actual microphone capture, hosted processing and real Search display acceptance remain unverified.

On restricted Windows environments, point `TEMP` and `TMP` to an existing writable directory and pass a fresh `--basetemp` directory to pytest. Generated reports, environments, runtime files and build artifacts are intentionally excluded from Git.

| Package | Responsibility |
|---|---|
| `team_1_ingestion` | Validated ingestion and SQLite storage |
| `team_2_analysis` | Claims, quantity normalization and disagreement analysis |
| `team_3_evidence_ui` | Evidence retrieval/adjudication, dashboard and exports |
| `integration` | Settings, orchestration, caching, budgets, CLI and integration tests |

The packages communicate through dictionaries. Shared contracts and reference fixtures remain in `build_handoffs/reference/` because automated tests use them. Private copies match `contract_v1_1.py`, which accepts existing v1 artifacts and adds truthful Gemini usage/schema 1.1.0. The original v1 reference is retained. Planning documents, handoff notes and presentation material are not part of the tracked application.
