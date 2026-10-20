# Team 3: Evidence Verification and Streamlit Dashboard (`althea_evidence_ui`)

This package implements **Person 3's** deliverables for the Althea AI debate fact-checking platform:
1. **Evidence Verification Pipeline**: Grounded search retrieval, per-claim adjudication against retrieved evidence, failure isolation by pair, and strict semantic validation against the frozen v1.0.0 wire contract.
2. **Streamlit Dashboard**: A local, single-user Streamlit user interface featuring transcript review, claim ledger filtering, disagreement cards, evidence citation inspector, and human-readable JSON/Excel BOM CSV exports.
3. **Fixture Backend & CLI**: Zero-network offline execution against the reference Riverton debate fixture, alongside full CLI tooling.

---

## Folder Layout

```text
team_3_evidence_ui/
  pyproject.toml                  # Package definition and dependencies
  app.py                          # Standalone Streamlit launch entry point
  .env.example                    # Template environment variables
  README.md                       # This documentation
  HANDOFF.md                      # Integration handoff brief and test record
  fixtures/                       # Frozen reference inputs and outputs
    transcript.json
    analysis.json
    verification.json
    reference_snapshot.json
    contract_v1.schema.json
  src/althea_evidence_ui/
    __init__.py                   # Public API exports
    __main__.py                   # CLI tool runner
    _contract.py                  # Frozen v1.0.0 wire contract (byte-identical)
    errors.py                     # Safe runtime exceptions (AltheaError, ContractError, etc.)
    validation.py                 # Semantic validation, URL normalization, canonical digests
    grounding.py                  # Retriever seam (Gemini Google Search Grounding & Fixtures)
    adjudication.py               # Judge seam (Gemini structured adjudication & Fixtures)
    verification.py               # VerificationService orchestrator
    fixture_backend.py            # Complete offline DashboardBackend implementation
    exports.py                    # UTF-8 Snapshot JSON & Formula-Safe Excel BOM CSV exports
    dashboard.py                  # 4-tab Streamlit UI implementation
    prompts/
      retrieve_v1.txt             # Neutral factual search prompt
      adjudicate_v1.txt           # Structured claim adjudication prompt
  tests/
    test_validation.py            # Semantic contract and citation rules
    test_verification.py          # Isolation, budget limits, 4-pair cap
    test_fixture_backend.py       # In-memory storage, review invalidation, reanalysis
    test_exports.py               # CSV formula escaping & JSON stability
    test_dashboard.py             # Streamlit AppTest verification
```

---

## Setup & Installation

All commands are run from `team_3_evidence_ui/` on Windows PowerShell:

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install package in editable mode with development dependencies
python -m pip install -e ".[dev]"
```

---

## Running the Test Suite

Run unit and integration tests with pytest:

```powershell
python -m pytest -v
```

---

## Running the CLI

### Display CLI help:
```powershell
python -m althea_evidence_ui --help
```

### Run offline fixture verification on Riverton sample:
```powershell
python -m althea_evidence_ui --mode fixture --input fixtures/analysis.json --transcript fixtures/transcript.json --pairs pair_0001 --output out/verification.json
```

### Run live Gemini Search Grounding verification (requires ADC or `PROJECT_ID`):
```powershell
python -m althea_evidence_ui --mode live --input fixtures/analysis.json --transcript fixtures/transcript.json --pairs pair_0001 --output out/live_verification.json --project-id <YOUR_PROJECT_ID>
```

---

## Launching the Streamlit Dashboard

Run the standalone Streamlit dashboard:

```powershell
python -m streamlit run app.py
```

The application opens at `http://localhost:8501`:
- **Sidebar**: Mode selection (`Sample demo (Offline Fixture)`) and saved jobs history.
- **Transcript Tab**: Chronological turns, speaker badges, mm:ss timing, audio playback (or notice if unlinked), and editable review form that safely invalidates downstream artifacts on save.
- **Claims Tab**: Filterable ledger by speaker, subject, and checkability.
- **Disagreements Tab**: Priority-sorted conflict cards showing exact quotes, explanation, and safely computed numeric differences, with pair selection checkboxes for evidence checking.
- **Evidence & Export Tab**: Independent claim verdicts ("Supported by retrieved evidence", "Refuted by retrieved evidence", "Insufficient evidence", "Needs context"), source citations with origin badges, Google Search entry point attribution, and one-click JSON/CSV downloads.

---

## Public Python API

Other modules or integration orchestrators can import:

```python
from althea_evidence_ui import (
    VerificationService,
    validate_verification,
    render_app,
    claims_csv,
    snapshot_json,
    FixtureBackend,
    AltheaError,
    ContractError,
)
```
