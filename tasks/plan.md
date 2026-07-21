# Plan: Test suite and CI for hf-to-r2

Spec: ../SPEC.md

## Dependency graph

```
T1 scaffolding (conftest, fakes, requirements)
 ├── T2 unit tests: normalize_repo_id      (independent of T3/T4)
 ├── T3 unit tests: filtering/args/env     (independent of T2/T4)
 └── T4 regression tests: stream_to_r2     (needs fakes from T1)
      └── CHECKPOINT A: full suite green locally
           └── T5 CI workflow + push
                └── CHECKPOINT B: CI green on GitHub
```

## Key design facts (from reading hf_to_r2.py)

- Module reads R2 env vars at import time → conftest must set env **before**
  importing, and import via `importlib.util` from the repo root path.
- `stream_to_r2(client, hf_url, r2_key, filename, token)` takes the R2 client
  as a parameter → a fake client needs no boto3 patching.
- It calls module-level `requests.get` → monkeypatch `mod.requests.get`.
- Backoff uses module-level `time.sleep` → monkeypatch to no-op.
- `CHUNK_SIZE` is a module global read at call time → shrink it in tests so
  multi-part scenarios use tiny payloads.
- `err()` calls `sys.exit(1)` → assert `SystemExit` for validate_env tests.
- Filter logic and `--include`/`--all` resolution live inside `main()` →
  test the resolution rule directly (argparse) and the fnmatch behavior
  against `DEFAULT_INCLUDE`; full `main()` E2E is out of scope (network API).

## Tasks

### T1 — Test scaffolding
Create `tests/conftest.py` (env setup + module import fixture, `FakeR2Client`,
`make_fake_get` factory with programmable disconnects), `requirements.txt`,
`requirements-dev.txt`.
**Verify:** `pytest tests/ --collect-only` succeeds; a trivial smoke test passes.

### T2 — Unit tests: normalize_repo_id
All URL/id forms from the spec, including error cases (SystemExit via err()).
**Verify:** tests fail against a deliberately wrong expectation, pass against code.

### T3 — Unit tests: filtering, arg defaults, validate_env
Default patterns keep/drop matrix, --include override, --all, --exclude,
missing env vars exit.
**Verify:** suite passes; keep/drop matrix matches spec table exactly.

### T4 — Regression tests: stream_to_r2
Happy path (multi-part + single-part), 1 and 2 disconnects with byte-identity
assertions, Range offsets land on committed boundaries, retry-budget reset on
progress, exhaustion → abort + raise + attempt count, non-206 resume → abort,
early failure → abort.
**Verify:** full suite green; deliberately break resume logic in a scratch
copy to confirm tests catch it (mutation check).

### CHECKPOINT A
Full suite passes locally in <5s. Review coverage against SPEC acceptance
criteria checklist.

### T5 — CI workflow
`.github/workflows/ci.yml`: pytest on push/PR to main, Python 3.11–3.13
matrix. Commit everything, push.
**Verify:** `gh run watch` shows green on all matrix legs.

### CHECKPOINT B
CI green on GitHub → lifecycle continues to review/simplify/ship.
