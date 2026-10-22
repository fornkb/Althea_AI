# Althea AI

A local application for reviewing spoken claims, comparing speakers and checking selected disagreements against retrieved evidence.

## Run

Requires Python 3.12. From the repository root in PowerShell:

```powershell
./setup.ps1
./run.ps1
```

On Windows, double-click **run.bat** to start the app and open it in your browser. Keep its console window open; press Ctrl+C there to stop the server. On a fresh checkout the batch file runs setup automatically if `.venv` is missing. Use `run.bat --check` for dependency checks without starting the server. After pulling a folder-layout change, rerun `setup.ps1` to refresh editable package paths.

The Flask app opens at **http://127.0.0.1:5000**. It uses plain JavaScript and CSS, with real URLs, browser Back/Forward and reload support. No Node build is required. The top navigation has three sections:

- **Home:** Upload or drop audio, or use the microphone recorder. Each analysis opens its own page with Transcript, Claims, Disagreements and Evidence views.
- **History:** Open saved conversations across the sample, Gemini and Cloud workspaces without new provider calls.
- **Settings:** Select the analysis provider, enter your Gemini key and configure models. With Remember these settings checked, configuration is saved in the Git-ignored `.env` file and survives restarts. Keys are never sent back to the browser or included in saved jobs or exports.

Analysis runs in a background worker. Navigation stays available while it processes. If you move to another page, completion shows a link to the result and leaves you on that page. Upload selections and recording previews remain available when navigating within the app. A full browser reload clears unsent files, while accepted background work continues on the server.

Choose **Explore the sample** for a fictional two-speaker debate that works offline without credentials. Its eight turns produce seven claims, three assessed pairs and one eligible disagreement. Evidence is explicitly synthetic; both budget claims are refuted. There is no sample audio or live search implied.

## Audio and provider setup

**Gemini API (default):** In Settings, select Gemini API key, enter a key and choose Save settings. Remember these settings saves it locally across restarts; uncheck that option for server-session-only changes. Alternatively, set `GEMINI_API_KEY` in the root `.env` file and restart the app. No Google Cloud project or ADC is required for this route. Audio transcription, text analysis and evidence retrieval default to `gemini-3.5-flash-lite`. See [Google's model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite).

Audio/text free-tier eligibility and quotas depend on the key's project. Google lists Search grounding for this model as requiring the paid tier, so web evidence checks may be unavailable on a free-tier key; leave the evidence checkbox off to run audio/text analysis only. See [Google's pricing](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite). The app does not change billing or automatically switch providers.

**Google Cloud:** Configure your existing project, model access and Application Default Credentials, then select Google Cloud / Vertex AI in Settings. The native transcription model is `gemini-3.5-transcribe`; availability and annotations depend on account/model support.

Install both FFmpeg and ffprobe and add their executable directory to PATH before processing audio. Settings reports missing binaries. Use the distributions linked by [FFmpeg](https://ffmpeg.org/download.html). The sample and complete Transcript JSON import do not require these binaries.

Audio is English, MP3/WAV, up to five minutes. Gemini inline audio is limited to 13 MiB; the Cloud route allows 20 MiB. Record audio uses an AudioWorklet to capture mono PCM WAV at 16 kHz. Capture starts only after you choose the microphone button and grant browser permission; it stops after five minutes or when leaving the workspace. Listen back before choosing Analyze. Recording, preview and page navigation do not start model requests.

Use recordings you are authorized to process. Analyze and evidence actions transmit audio/text to the selected provider. Gemini receives the measured clip duration and returns relative `MM:SS.mmm` timestamps, which the app converts to seconds. Speaker turns/timings remain model-generated and approximate; review playback, names, numbers and negation. Missing, reversed or out-of-range annotations are rejected with a timing error rather than invented or silently adjusted. Native Cloud annotations also need human review.

To import complete Transcript JSON, choose a `.json` file through Workspace → Upload audio.

## Configuration

Only the application loads the `.env` file in the repository root. Copy `.env.example` to `.env` if needed, paste your key after `GEMINI_API_KEY=`, and restart the app. `.env` is ignored by Git; never put your real key in `.env.example`. Environment variables take precedence over `.env`.

| Variable | Purpose |
|---|---|
| `ALTHEA_PROVIDER` | `gemini` (default) or `vertex` for CLI/configuration |
| `GEMINI_API_KEY` | Developer API key; UI entry is also available |
| `GOOGLE_CLOUD_PROJECT` | Existing Cloud project |
| `GOOGLE_CLOUD_LOCATION` | Model location; default `global` |
| `ALTHEA_TRANSCRIBE_MODEL` | Native Cloud transcription model |
| `ALTHEA_GEMINI_AUDIO_MODEL` | Gemini audio-understanding model |
| `ALTHEA_TEXT_MODEL` | Extraction/comparison/adjudication model |
| `ALTHEA_GROUNDING_MODEL` | Grounded retrieval model |
| `ALTHEA_DATA_DIR` | Local data directory; default `data` |

Key entry and ordinary preflight make no external request. Remove saved key in Settings clears the active server key and, when Remember these settings is checked, the key in `.env`. Environment variables take precedence again on the next restart. The web server binds only to `127.0.0.1`, rejects unrelated Host/Origin values and requires a session CSRF token for mutations.

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

Incremental checks preserve other pairs. Failed refresh preserves the selected saved verdict and source dates, with a notice that the latest check did not finish. Job locks and transactional counters protect concurrent actions. Interrupted jobs are marked partial/failed on startup without automatically resuming provider calls.

Evidence retrieval and adjudication are separate requests. Native metadata supplies source links. A grounded AI summary is labelled accordingly, not presented as a website quotation. Claims are assessed independently; the app does not select a debate winner or produce a confidence percentage. CSV exports escape formula-leading textual cells; JSON retains original content.

Disagreements also shows **Needs context** comparisons. Spoken event counts such as “six times” and “four times” are normalized without treating speed/price multipliers as counts. Lexical matching retains qualified topic labels; adjacent event-count replies can receive a bounded contextual comparison with surrounding transcript turns even when their topic labels share no words. Missing scope is retained, and no numeric difference or contradiction is manufactured. Select a context-needed comparison to investigate sources; evidence may still leave it unresolved. Reanalyze transcript refreshes claims/comparisons without retranscribing audio. Stage versions and prompt hashes invalidate older cached analyses automatically on reanalysis.

## Development and tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pytest
python -m althea_app.web --no-browser
```

The latest offline regression run passed **282 tests**, with five live tests deselected, including seven Flask integration tests and regressions for event counts, ambiguous replies, conservative scope checks, evidence retrieval on context-needed comparisons and older saved artifacts. Browser checks covered Home/Settings navigation, browser Back, navigation during a sample analysis, result tabs and opening the existing MP3 result. The Trump–Clinton saved transcript was reanalyzed with the unchanged Gemini 3.5 Flash-Lite model: four claims and one context-needed six-versus-four comparison were produced in three text requests, with no audio or web search request. The comparison and enabled Check evidence action were verified in the browser. This verifies processing, not transcription accuracy or real-world truth. Human-labelled accuracy evaluation, actual microphone capture and real Search display acceptance remain unverified.

On restricted Windows environments, point `TEMP` and `TMP` to an existing writable directory and pass a fresh `--basetemp` directory to pytest. Generated reports, environments, runtime files and build artifacts are intentionally excluded from Git.

| Package | Responsibility |
|---|---|
| `ingestion` | Validated ingestion and SQLite storage |
| `analysis` | Claims, quantity normalization and disagreement analysis |
| `evidence_ui` | Evidence retrieval/adjudication and exports; optional legacy dashboard |
| `app` | Flask web UI, settings, orchestration, caching, budgets, CLI and tests |

The packages communicate through dictionaries. `reference/` holds shared contracts and test fixtures. Private copies match `contract_v1_1.py`, which accepts existing v1 artifacts and adds truthful Gemini usage/schema 1.1.0. The original v1 reference is retained. Planning documents, handoff notes and presentation material are not part of the tracked application.

```text
app/                  Application, CLI and integration tests
  src/althea_app/
    web.py            Flask API and local server
    templates/        HTML application shell
    static/           JavaScript, CSS, microphone worklet and icons
  streamlit_app.py    Optional legacy entry point; not used by run.bat
ingestion/            Audio ingestion and storage package
analysis/             Claims and disagreement analysis package
evidence_ui/          Evidence checking and dashboard package
reference/            Shared contracts and reference fixtures
run.bat               Windows double-click launcher
run.ps1               PowerShell launcher
setup.ps1             Dependency setup
```
