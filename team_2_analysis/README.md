# Althea AI — person 2 analysis

An independently installable Python component that extracts factual claims from a
validated transcript and identifies **potential disagreements**. Includes an offline
fictional sample, deterministic arithmetic, a Google Cloud text adapter, and fakes for
integration tests. It does not determine factual truth or choose a debate winner.

## Setup and run

Run these PowerShell commands from `team_2_analysis/` with Python 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -m althea_analysis --mode fixture --input fixtures/transcript.json --output out/analysis.json
```

Fixture mode requires no credentials or network. The default fixture provider accepts
only the supplied Riverton transcript; other offline scenarios use `ScriptedTextProvider`.
The fictional transcript has no audio recording. Reference expected data is supplied
separately from the output actually computed by this implementation.

The sample yields seven claims and three assessed pairs:

| Claims | Assessment | Absolute difference |
|---|---|---|
| 10 vs 12 million USD annual transport budget, 2024 | numeric_discrepancy | 2000000 currency |
| Unemployment in 2023 vs 2024 | different_scope | null |
| 2.5 million vs 2500000 USD library allocation, 2025 | compatible | 0 currency |

The opinion is excluded. The final ambiguous “it increased by five percent” retains
unknown subject, metric, time and geography. Neither budget claim is declared false
by this module; evidence adjudication belongs to person 3.

## Live mode

The constructor receives an ordinary settings dictionary. Imports do not read secrets,
initialize clients, create files or download anything. Live requests explicitly use
Vertex, Google Application Default Credentials (ADC), and the configured project.
They never fall back to an API-key billing route.

Configure an authorized Cloud project with the selected model enabled, then use ADC:

```powershell
gcloud auth application-default login
$env:GOOGLE_CLOUD_PROJECT = "your-project-id"
$env:GOOGLE_CLOUD_LOCATION = "global"
$env:ALTHEA_TEXT_MODEL = "gemini-2.5-flash"
python -m althea_analysis --mode live --input fixtures/transcript.json --output out/live_analysis.json
```

The CLI reads these identifiers only in live mode. `.env.example` is documentation;
the package does not automatically load `.env`. The model, region, access and credit
eligibility require checking for the user's account. The live smoke test was **skipped**:
no project identifier was configured. No live success or accuracy is claimed.

To explicitly run the optional, billable smoke test after configuring the project:

```powershell
$env:ALTHEA_RUN_LIVE = "1"
python -m pytest -m live -q
```

Official documentation checked on 17 October 2026:
[structured output](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output),
[Google Gen AI SDK](https://github.com/googleapis/python-genai),
[ADC](https://cloud.google.com/docs/authentication/provide-credentials-adc).
The installed SDK's `HttpOptions`, `HttpRetryOptions` and `GenerateContentConfig`
fields were also exercised with a simulated client. Account access remains unverified.

## Public API

```python
from althea_analysis import AnalysisService, AttemptBudget, validate_analysis

# Integration passes its persisted job-wide budget in place of AttemptBudget.
service = AnalysisService({"mode": "fixture"})
analysis = service.analyze(transcript_dictionary, budget=AttemptBudget(20), progress=print)
validated_dictionary = validate_analysis(analysis, transcript_dictionary)
```

Exports: `AnalysisService`, `validate_analysis`, `normalize_quantity`,
`make_candidate_pairs`, `AttemptBudget`, `AnalysisError`, `EXTRACTION_VERSION`,
`COMPARISON_VERSION`, `NORMALIZATION_VERSION`, `MATCHING_VERSION`.

Providers implement:

```python
generate_json(*, operation, system, payload, response_schema,
              max_output_tokens, budget) -> tuple[dict, dict]
```

`operation` is extraction or comparison. Return parsed JSON and a frozen `Usage`
dictionary. `FixtureTextProvider` makes zero external attempts. `ScriptedTextProvider`
simulates events and reserves a shared budget slot before each simulated call by
default. For live providers, **the provider owns retries and budget reservation**.
Do not consume again in the integration wrapper. Set `mode = "fixture"` on custom
offline providers if using service fixture mode; a live adapter is refused there.

The bundled `VertexTextProvider` permits three total attempts per logical operation,
including at most one content/schema repair. SDK retry attempts are set to one;
application retries handle only 429, 5xx and transient transport errors, with bounded
backoff/jitter. Permanent 4xx/auth/configuration failures are not retried. The shared
budget is consumed immediately before every external attempt. A custom provider
must enforce the same three-attempt contract, including calls with `_repair = True`.
`max_provider_attempts` is checked as a settings limit; the caller must construct its
shared persisted budget using that limit. `AttemptBudget` is a standalone replacement,
not a replacement for job-wide persistence. Limits count attempts, not currency cost.

The service performs one extraction and at most one batched comparison operation;
repair is bounded inside those operations. Safely deterministic pairs need no model
comparison. Omissions, extras, duplicates and reversed returned pairs fail comparison
after one repair. No successful Analysis is returned for a failed comparison stage.
Safe RuntimeError subclasses expose `code`, `stage`, `retryable` and a brief message.

## Data and semantic rules

Wire dictionaries follow the frozen contract byte-for-byte in `src/althea_analysis/_contract.py`.
Provider-only DTO schemas live in `dto.py`; reference schemas are inlined and nullable
fields adapted to the supported Vertex Schema subset. Responses remain strictly
validated: unknown fields are never silently removed. Prompts are versioned files.

Every claim needs an exact supporting quote from its own speaker. Python relocates
unique exact quotes regardless of proposed offsets. Repeated quotes require valid
disambiguating offsets; ambiguous/forged spans are rejected, repaired once, then
dropped with an issue. Entirely unusable nonempty proposals fail explicitly, including
a repair that attempts to erase all invalid proposals into an empty result.

Claims sort by first source position, then proposition for ties. Identical propositions
and scope from the same speaker are merged with multiple ordered spans; different
speakers remain separate. The first 30 validated claims are kept, with an issue for
truncation. A human/LLM must establish atomicity and context entailment; exact quote
matching alone does not prove that a paraphrased proposition follows from the quote.

Quantity parsing uses `Decimal` and explicit wording. Magnitudes, common explicit
currencies, percent, percentage points, metres/kilometres, kg/grams, negative numbers,
small English number words, ranges and bounds are supported. Bare `$` requires
explicit currency context. `m` means metres; uppercase `M` can mean million. A year
matching the claim's period is not used as its quantity. Unsupported wording returns
null and retains the original quote plus a context issue. No currency exchange,
implicit reporting-period conversion or tolerance for “about” is invented.

Candidate selection enumerates every cross-speaker pair, then screens for topical
plausibility. Known subjects/metrics require equal canonical labels or at least 0.5
Jaccard word overlap in both fields. Unknown metrics require proposition overlap of
at least 0.45 and three shared meaningful nonnumeric terms. Number overlap never
creates a match. Extracted canonical labels preserve paraphrase pairs.

Eligible candidates rank by: both normalized subject/metric equal; count of equal
fields; sum of subject/metric Jaccard overlaps; proposition overlap; inverse source
distance. Claim ID tuples break ties. Common stopwords and numeric tokens do not
contribute. At most 60 are assessed, with a truncation issue. This is a bounded
heuristic shortlist and can miss disagreements; it is not exhaustive debate coverage.

Known scope differences are checked before arithmetic. Null scope is unknown, never
a wildcard; `not_applicable` is explicit non-applicability. Simple subtraction requires
complete equal subject/metric/time/geography/population/basis, equal qualifiers,
units/currency, and exact `eq` values. Bounds/approximation and percent versus point
changes receive hosted assessment or abstention, with null numeric difference.
All pair outputs sort by ID tuple before assigning sequential pair IDs. IDs use the
specified full canonical SHA256 identities; explanations and methods affect analysis ID.

## Validation status and limits

All **96 offline tests passed**. See the root README and requirements-dev.txt for integrated setup and tested dependencies.
Exported public Analysis and provider DTO schemas are in `schemas/`. Tests assert semantic
outcomes, quote integrity, injection handling, malformed JSON, bounded repairs,
budget exhaustion and no fixture networking. They use synthetic inputs and simulated
provider responses. They **do not establish hosted extraction quality** or model
resistance to prompt injection on real transcripts.

No human-labelled evaluation set was supplied. Extraction precision/recall and
disagreement precision/recall are therefore **not measured**. The synthetic reference
fixture and test expectations are engineering checks, not human gold labels.
