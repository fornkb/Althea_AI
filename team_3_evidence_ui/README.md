# Althea AI — Person 3

Independent evidence verification package and Streamlit dashboard. The standalone dashboard uses an in-memory fictional backend and requires neither other teams nor cloud credentials. Live verification is available through the CLI/provider APIs; the real application backend remains the final integration phase.

## Setup and run (PowerShell, from this folder)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m streamlit run app.py
```

For this workspace, local dashboard dependencies are also installed in the ignored `.deps` directory. `./run_sample.ps1` adds `src` and `.deps` and uses the installed Python 3.12. It serves only on localhost, with a 20 MiB uploader limit and telemetry disabled. The sample runs offline. Session history is cleared when the server/session ends; durable history belongs to the final backend.

Choose Analyze, inspect the four tabs, select a disagreement and choose Check selected. The original budget pair's synthetic record refutes both claims. Sample evidence is explicitly fictional. Uploads require the integrated live backend and never masquerade as processed audio. The sample has no recorded audio.

Review transcript names, text, speaker assignments and timing in the review form. Save clears downstream results. The unchanged sample can be deterministically reanalysed. Custom edits remain saved but require a live analysis backend; stale reference claims are never reused. Downloads and filters do not call providers.

## Verification CLI

```powershell
python -m althea_evidence_ui --mode fixture --input fixtures/analysis.json --transcript fixtures/transcript.json --pairs pair_0001 --output out/verification.json
# Empty requested selection is valid and makes no calls:
python -m althea_evidence_ui --mode fixture --input fixtures/analysis.json --transcript fixtures/transcript.json --output out/not-selected.json
```

For live verification, configure [Google Cloud ADC](https://cloud.google.com/docs/authentication/provide-credentials-adc) and model access, then:

```powershell
$env:GOOGLE_CLOUD_PROJECT='your-project-id'
$env:GOOGLE_CLOUD_LOCATION='global'
$env:ALTHEA_GROUNDING_MODEL='gemini-2.5-flash'
$env:ALTHEA_TEXT_MODEL='gemini-2.5-flash'
python -m althea_evidence_ui --mode live --input path/to/analysis.json --transcript path/to/transcript.json --pairs pair_0001 --output out/verification.json
```

Use real validated transcript/analysis data for substantive live evaluation. The fictional Riverton fixture does not provide an accuracy benchmark. Account/model availability and credit eligibility must be checked; there is no fallback to another billing service or synthetic answers. Partial failures still write usable JSON and cause nonzero CLI exit status. Zero eligible/selected pairs exit successfully without network access.

## APIs and integration

```python
from althea_evidence_ui import (
    VerificationService, validate_verification, FixtureBackend,
    render_app, claims_csv, snapshot_json,
)
# Shared budget must expose consume(stage), throwing code='BUDGET_LIMIT'.
verification = VerificationService(settings).verify(transcript, analysis, pair_ids, budget=budget)

# Final integration supplies zero-argument backend factories, instantiated lazily.
render_app({'Sample demo': lambda: FixtureBackend(), 'Live': lambda: YourBackend(settings)})
```

The UI depends only on the frozen DashboardBackend protocol: `run`, `load`, `list_jobs`, `save_review`, `reanalyze`, `verify_pairs`. `refresh_verification(job_id, pair_ids, progress=None)` is optional; the UI hides Refresh unless the backend implements it. The final backend handles persistent caching, merging incremental verification by pair (including attribution), job-wide attempts and cumulative four-pair reservations using `analysis_id:pair_id`. Person 3's service limits each request to four and validates the eligible universe. Upstream packages are never imported.

Retriever seam: `retrieve(*, transcript, claims, pair, budget) -> (Evidence[], Usage[], GroundingAttribution|None)`. Judge seam: `judge(*, claims, pair, evidence, budget) -> (PairVerdict, Usage[])`. Adapters own per-attempt accounting; the service never double-charges. Each operation has at most three attempts for transient errors, with SDK retries disabled. Invalid structured responses fail without a hidden repair loop. Pair failures are isolated. Return every eligible pair exactly once as checked or unverified.

Retrieval is a Google Search grounded call without a JSON schema. Adjudication is a separate structured call without search tools. Only native support-to-source-index mappings produce `grounded_summary`; unmapped source URLs remain `metadata_only` and cannot support/refute a claim. Native source URLs are validated and deduplicated; redirect URLs remain as returned and are not claimed to be publisher URLs. No URLs are fetched by this package. Missing publishers/dates remain null. Grounding text is an AI summary, not a source quotation. Only the labelled fixture uses a synthetic retrieved passage.

Judges are given exact scope and asked to abstain for wrong historical periods, missing context or inadequate evidence. Structural validation cannot establish that a source interpretation is factually correct; human-labelled evaluation remains necessary. Both claims may be refuted. Prompt injection tests establish reference/payload rejection, not hosted-model immunity.

Exports: full UTF-8 Snapshot JSON retains all original content, origin labels, usage, issues and attribution. CSV has a UTF-8 BOM and proper multiline quoting. Text cells beginning with spreadsheet formula characters (including leading whitespace) get a CSV-only apostrophe; canonical numeric values remain numeric text. No data is changed in JSON.

## Search attribution boundary

The live retriever records the provider's actual native Search HTML separately. The UI renders it unchanged in an isolated Streamlit HTML component only when that exact attribution was observed by the live adapter in the current process. Imported/stored HTML is retained for export but never trusted for execution. In that case the UI displays an unresolved-attribution notice. Full live display acceptance, including saved-result attribution behavior and chip height/branding, remains a handoff limitation until verified against a real account. No arbitrary model/page HTML is rendered.

Official references checked for implementation: [grounding and Search display requirements](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/grounding-with-google-search), [structured output](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output), [SDK](https://github.com/googleapis/python-genai). See the [root README](../README.md) for current validation status and live limitations.
