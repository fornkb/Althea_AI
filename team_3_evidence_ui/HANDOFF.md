# Team 3 Handoff: Evidence Verification & Streamlit Dashboard

**Delivered By**: Person 3 AI Agent  
**Date**: October 2026  
**Package**: `althea_evidence_ui` in folder `team_3_evidence_ui/`  
**Binding Contract**: Althea Wire Contract v1.0.0 (`src/althea_evidence_ui/_contract.py` byte-identical to `reference/contract_v1.py`)

---

## 1. Public Imports & Exported Interface

Integration code should import only from `althea_evidence_ui`:

```python
from althea_evidence_ui import (
    # Core verification service
    VerificationService,
    # Semantic validator
    validate_verification,
    # UI renderer
    render_app,
    # Export utilities
    claims_csv,
    snapshot_json,
    # Complete offline fixture backend
    FixtureBackend,
    # Exceptions
    AltheaError,
    ContractError,
    BudgetLimitError,
    ProviderError,
)
```

### Signatures & Seams:

```python
class VerificationService:
    def __init__(self, settings: dict, *, retriever=None, judge=None): ...
    def verify(self, transcript: dict, analysis: dict, pair_ids: list[str], *,
               budget=None, progress=None) -> dict: ...

def validate_verification(payload: dict, analysis: dict) -> dict: ...
def render_app(backends: dict[str, Callable[[], Any]]) -> None: ...
def claims_csv(snapshot: dict) -> bytes: ...
def snapshot_json(snapshot: dict) -> bytes: ...

class FixtureBackend:
    mode: str = "fixture"
    def run(self, source: dict[str, Any], *, verify: bool, progress=None) -> dict[str, Any]: ...
    def load(self, job_id: str) -> dict[str, Any]: ...
    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]: ...
    def save_review(self, job_id: str, transcript: dict[str, Any]) -> dict[str, Any]: ...
    def reanalyze(self, job_id: str, *, verify: bool, progress=None) -> dict[str, Any]: ...
    def verify_pairs(self, job_id: str, pair_ids: list[str], progress=None) -> dict[str, Any]: ...
    def refresh_verification(self, job_id: str, pair_ids: list[str], progress=None) -> dict[str, Any]: ...
```

---

## 2. Source-Origin Distinction & Citation Rules

Per the frozen specification, evidence records distinguish their provenance through `content_origin`:

1. `grounded_summary`: Generated text from Gemini that is linked to a grounding chunk index by native metadata. It is labelled in the UI as **"Source-backed AI summary"**, never verbatim quotation.
2. `metadata_only`: Sources returned in search metadata without mapped passage text. Its `content` is `null`. Per the semantic validation rules, `metadata_only` evidence **cannot** establish `supported` or `refuted` status.
3. `retrieved_excerpt`: Used only for genuine verbatim passages returned by providers or the labelled reference fixture. In the Riverton fixture, it is explicitly labelled throughout the UI as **"Synthetic evidence — demonstration only"**.

---

## 3. Protocol Usage & Integration Notes

- **Lazy Factory Backend Pattern**: `render_app` expects a dictionary mapping display labels to zero-argument factories:
  ```python
  backends = {
      "Sample demo (Offline Fixture)": lambda: FixtureBackend(settings),
      "Live Integration": lambda: IntegrationBackend(settings), # In final integration phase
  }
  ```
  The UI lazily instantiates the backend once per session upon selection, ensuring standalone testing requires no cloud credentials.
- **Transcript Invalidation**: When `backend.save_review` is invoked, downstream `analysis` and `verification` are set to `None`, status becomes `ready`, and a new `transcript_id` is computed using canonical SHA256 digest over `{content_sha256, language, duration_s, speakers, segments}`.
- **Deterministic Reanalysis**: In `FixtureBackend`, reanalysis succeeds only if the reviewed segments remain unchanged from the reference fixture. Arbitrary text edits correctly return status `failed` with an Issue stating `"Custom edited analysis requires live backend"`, ensuring stale synthetic claims are never erroneously presented.

---

## 4. Tested Dependency Versions

Tested on Windows 11 with Python 3.11.9:

| Package | Version |
|---|---|
| `python` | `3.11.9` |
| `pydantic` | `2.14.1` |
| `pydantic-core` | `2.50.1` |
| `streamlit` | `1.66.0` |
| `google-genai` | `2.31.0` |
| `pytest` | `9.1.1` |

---

## 5. Test Suite & Verification Results

All 28 unit and integration tests passed:

```text
tests/test_dashboard.py::test_dashboard_renders_successfully PASSED
tests/test_dashboard.py::test_dashboard_sample_run_interaction PASSED
tests/test_dashboard.py::test_dashboard_rerun_does_not_call_external_providers PASSED
tests/test_exports.py::test_neutralize_csv_formula PASSED
tests/test_exports.py::test_claims_csv_excel_bom_and_escaping PASSED
tests/test_exports.py::test_snapshot_json_preserves_unmodified_data PASSED
tests/test_fixture_backend.py::test_fixture_backend_run_sample PASSED
tests/test_fixture_backend.py::test_fixture_backend_run_without_verify PASSED
tests/test_fixture_backend.py::test_fixture_backend_save_review_and_invalidation PASSED
tests/test_fixture_backend.py::test_fixture_backend_reanalyze_unchanged_vs_edited PASSED
tests/test_fixture_backend.py::test_fixture_backend_verify_pairs PASSED
tests/test_fixture_backend.py::test_fixture_backend_load_not_found PASSED
tests/test_validation.py::test_reference_verification_passes PASSED
tests/test_validation.py::test_url_validation_and_normalization PASSED
tests/test_validation.py::test_reject_javascript_url_in_evidence PASSED
tests/test_validation.py::test_metadata_only_cannot_support_or_refute PASSED
tests/test_validation.py::test_both_claims_refuted_allowed PASSED
tests/test_validation.py::test_one_supported_one_insufficient_allowed PASSED
tests/test_validation.py::test_wrong_pair_or_claim_reference_rejected PASSED
tests/test_validation.py::test_invalid_evidence_id_sequence_rejected PASSED
tests/test_validation.py::test_ineligible_pair_in_results_rejected PASSED
tests/test_validation.py::test_verification_id_digest_mismatch_rejected PASSED
tests/test_verification.py::test_zero_network_fixture_verification PASSED
tests/test_verification.py::test_exceeding_max_verify_pairs_rejected PASSED
tests/test_verification.py::test_duplicate_pair_ids_rejected PASSED
tests/test_verification.py::test_empty_eligible_pairs_returns_empty_valid_verification PASSED
tests/test_verification.py::test_failure_isolation_by_pair PASSED
tests/test_verification.py::test_budget_exhaustion_handling PASSED

============================= 28 passed in 4.24s ==============================
```

---

## 6. CLI Smoke Test Result

Executed:
```powershell
python -m althea_evidence_ui --mode fixture --input fixtures/analysis.json --transcript fixtures/transcript.json --pairs pair_0001 --output out/verification.json
```
- **Exit Code**: `0`
- **Output Digest**: `ve_6adadf5e05bdfaa2c12d813842510eea1a799028a73118acd5e7220ccc53eb35` (Exact byte-for-byte match with `reference/verification.json`).

---

## 7. Live Provider Checks & Environment Requirements

- **Live Mode Engine**: `GeminiGroundingRetriever` and `GeminiJudge` in `grounding.py` and `adjudication.py`.
- **API Call Separation**: Google Search grounding uses unstructured `generate_content` with `tools=[types.Tool(google_search=...)]`; structured claim adjudication runs as a subsequent separate call with `response_schema=PairVerdict`.
- **Auth**: Expects Google Cloud Application Default Credentials (`gcloud auth application-default login`) or `PROJECT_ID` in settings.
- **Provider Status**: In the offline development environment, Google Cloud credentials were not configured. The offline fixture pipeline is 100% operational with zero network calls. For live verification, supply `PROJECT_ID` and ensure Gemini 2.5 Flash Search Grounding is enabled on your GCP project. Failed live calls correctly return `ProviderError(code='PROVIDER_UNAVAILABLE')` and are isolated per pair into `unverified`, without substituting synthetic evidence.

---

## 8. Visual & Overflow Inspection

- Dashboard tested via Streamlit's `AppTest` simulation across initial load, run analysis, review form, and tabs navigation.
- Desktop display target: responsive multi-column layout at 1366x768.
- *Visual inspection on real browser window*: Marked **Not run directly in headless agent shell**; verified programmatically via Streamlit `AppTest` widget tree and syntax validation.
