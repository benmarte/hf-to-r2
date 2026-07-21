# TODO: Test suite and CI for hf-to-r2

- [x] T1: Test scaffolding — conftest.py (env-before-import, fakes in tests/fakes.py), requirements.txt, requirements-dev.txt.
- [x] T2: Unit tests for normalize_repo_id (all URL forms + error cases).
- [x] T3: Unit tests for filtering/arg defaults/validate_env.
- [x] T4: Regression tests for stream_to_r2 (resume, retry reset, exhaustion, abort paths, byte-identity). Mutation-checked.
- [x] CHECKPOINT A: full suite green locally (42 tests, ~0.1s).
- [x] T5: GitHub Actions CI (pytest, py 3.11-3.14, SHA-pinned actions, least-privilege permissions, Dependabot).
- [x] CHECKPOINT B: CI green on all matrix legs.
- [x] Ship review (parallel code-review / security-audit / test-engineering) — all findings fixed:
      4xx fail-fast in retry loop, hf-r2-ls heredoc injection, CI hardening, 8 extra tests.
- [x] Release v1.1.1.
