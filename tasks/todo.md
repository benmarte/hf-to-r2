# TODO: Test suite and CI for hf-to-r2

- [ ] T1: Test scaffolding — conftest.py (env-before-import, FakeR2Client, fake requests.get factory), requirements.txt, requirements-dev.txt. Verify: pytest collects + smoke test passes.
- [ ] T2: Unit tests for normalize_repo_id (all URL forms + error cases). Verify: pass.
- [ ] T3: Unit tests for filtering/arg defaults/validate_env. Verify: pass, keep/drop matrix matches spec.
- [ ] T4: Regression tests for stream_to_r2 (resume, retry reset, exhaustion, abort paths, byte-identity). Verify: pass + mutation check catches broken resume.
- [ ] CHECKPOINT A: full suite green locally, <5s, coverage matches SPEC checklist.
- [ ] T5: GitHub Actions CI (pytest, py 3.11-3.13), commit + push. Verify: CI green via gh run watch.
- [ ] CHECKPOINT B: CI green → proceed to review/simplify/ship.
