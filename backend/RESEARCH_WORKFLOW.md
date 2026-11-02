# Research lifecycle and Input Correction

This workflow replaces the globally exposed upload/result lifecycle. It does not change
Retrieve's original system/template, model configuration, Student label rules, or evidence algorithms.

## Persistence and access

`research_data/research.sqlite3` (override with `WEAVE_RESEARCH_ROOT`) stores experiments
and version JSON in transactional SQLite rows. `BEGIN IMMEDIATE` serializes mutations;
unique experiment/version-number and request-key constraints prevent duplicate versions.
Final `succeeded` and `failed` records cannot be updated through the store.
The access token is random; only its SHA-256 is stored. Treat the token as a secret.
The UI retains it in sessionStorage for reloads. No account or cross-device recovery is provided.

Each experiment has its own neutral video asset filename, upload SHA-256 and private original
filename/dataset ID. Ground Truth is a filename lookup, **not** video-content verification.
New versions use a unique `jobs/version_id/` workspace to stay within Windows path limits. Existing versions retain their saved artifact paths; no research job reads global
`backend/output/retrieve.jsonl`. Existing global analysis files remain untouched.

## API

All routes below except creation require `Authorization: Bearer <access_token>`.
Responses use `Cache-Control: no-store`.

| Method / path | Request | Response |
|---|---|---|
| POST `/experiments` | multipart `video` | 201 `{experiment, access_token}`; no model job |
| GET `/experiments/{id}` | — | permitted experiment metadata and locked judgment |
| GET `/experiments/{id}/video` | — | authenticated neutral-named video |
| POST `/experiments/{id}/human-judgment` | `{vote:"true" or "false", reason:""}` | locked experiment; identical resubmit is idempotent; changes return 409 |
| POST `/experiments/{id}/versions` | `{experiment_type:"baseline"}` | 201 new / 200 existing V1; requires locked human judgment |
| POST same | `{experiment_type:"input_correction",parent_version_id,field,value}` | new version or same existing parent/field/value version |
| GET `/experiments/{id}/versions` | — | `{versions:[...]}` ordered by version number |
| GET `/experiments/{id}/versions/{vid}/status` or `/result` | — | version metadata; result snapshots only after successful V1 |

Missing token returns 401, wrong token/experiment/version returns 404, invalid correction
returns 400, invalid lifecycle transition returns 409. Legacy `/upload`, `/status`, `/result`,
`/student_result` return 410, even when old output files exist. Old aggregate vote endpoints
remain separate from locked initial judgments. Translation still translates client-provided text.

V1 success is the single disclosure gate for GT and model snapshots. Original filenames
and dataset IDs are never in public experiment metadata. Vite blocks private namespaces and
dataset labels, including filesystem/raw-import paths. In production, serve **only `dist/`**
and proxy Flask; never mount the project/backend directory as a public static root.

## Execution and failure

A detached worker uses an OS file lock and a persisted SQLite queue, with one model stage
at a time. A second lock lives inside the model-stage process, including if its parent worker
dies. Polling resumes already-authorized pending work; it never creates a new version.
A running row without its worker lock is recovered as failed, retaining records, not replayed
as a fake success. Each stage times out after two hours (Retrieve retains its original retry limits).
Existing failed V1 is not silently retried; create a new experiment for a new baseline attempt.
Identical failed correction resubmission returns that failed version; change the correction or parent
to create a new experiment version. Automatic paid retries beyond Retrieve's existing policy are absent.

Baseline executes the same video/audio/frame/VLM/transcript/merge stages, now serialized rather
than concurrent, followed by Retrieve and the existing `run_student.py` entrypoint.

| Corrected input | Reused | Rerun |
|---|---|---|
| transcript | video preprocessing artifacts; override merged transcript | Retrieve regenerates Rc, Rv, K_int, K_ext/search; Student |
| Rc or Rv | preprocessing, other effective Rc/Rv value | Retrieve receives explicit frozen Rc/Rv inputs, regenerates knowledge/search; Student |

Transcript is not Rc. Missing/empty original text cannot be corrected. No K_int/K_ext,
GT, locked Human Judgment or model result editor is provided. The correction-specific Retrieve
input suffix requests regeneration from unverified user text; original core prompts/config remain
unchanged. The effective Rc/Rv override is enforced after generation, while generated candidates
remain in `generated_fields_before_override`. No parent K_ext or parent sources are reused.
Transcript correction regenerates both Rc/Rv, including replacing any prior *effective* overrides
in the child only. Parent snapshots remain intact. A model's semantic compliance is not guaranteed
by a mock; validate this on real authorized runs before scientific use.

## Audit and UI

Version rows retain parent, correction before/after/origin, planned/effective inputs, timestamps,
stage events, reused artifact hashes, effective source/result snapshots, and file SHA-256 manifest.
Retrieve records actual system prompt, user text, image paths, model/config and raw responses.
Student records the actual chat-template text, post-truncation token IDs/attention mask,
generation settings and raw response. Input trace is written before generation so failures keep
the effective input. Display prompts in the original UI remain labelled as display-only.

The two-page UI locks the initial judgment before explicit V1 start, restores the current session,
and selects immutable version snapshots together. Input Correction requires confirmation.
Successful child versions are selected and scrolled to comparison; failures retain/select V1
and show an error. Comparison includes input/source URL differences relative to the parent.
Switching versions never starts models or replaces the video player.

## Verification boundary

Run `python -B -m unittest discover -s tests -v`,
`node --test tests/evidence.test.mjs tests/research-security.test.mjs`, and `npm run build`.
Python models/Grounding are mocked; the actual Retrieve and Student entrypoint/trace code is
exercised separately. The Vite test uses only local HTTP and disables .env loading.
Vue tests use a custom renderer, not a real browser. GPU/model execution, retrieval quality,
external web access, production reverse-proxy rules and desktop/mobile visual behavior still
require authorized manual validation. File hashes are audit checks, not protection against a
trusted local administrator editing storage. Losing the session token requires a new experiment.
Feature 7 remains disabled; future ablation can use version parent/provenance/source references,
but must separately address source-derived K_ext removal.
