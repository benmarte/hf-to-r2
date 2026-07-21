# SPEC: Test suite and CI for hf-to-r2

## Objective

Give hf-to-r2 a professional-grade automated test suite and CI pipeline so that
every future change (and every release) is verified against regressions —
especially the resume-on-disconnect logic in `stream_to_r2`, which is the most
failure-prone code in the project.

**Target users:** maintainers of this repo (today: one person + AI agents).
The tests are the safety net that makes future releases trustworthy.

## Assumptions

1. Tests must never touch the network, HuggingFace, or a real R2 bucket —
   everything is mocked/faked in-process.
2. The production script's runtime behavior must not change. Refactoring
   `hf_to_r2.py` for testability is out of scope unless a test is impossible
   without it (none are — env vars can be set before import).
3. pytest is the test framework (Python community standard, zero config).
4. CI is GitHub Actions (repo already lives on GitHub).
5. No new release is cut for this work — tests and CI don't change the shipped
   artifact's behavior. v1.1.0 remains the latest release.

## Commands

```bash
# run the full suite locally
~/.venvs/hf-to-r2/bin/python3 -m pytest tests/ -v

# install dev dependencies
pip install -r requirements-dev.txt
```

## Project structure

```
hf-2-r2/
├── hf_to_r2.py            # production script (unchanged)
├── hf_r2_zshrc.zsh        # zsh integration (unchanged)
├── tests/
│   ├── conftest.py        # env setup before import, shared fakes (FakeR2Client, FakeResponse)
│   ├── test_normalize_repo_id.py
│   ├── test_filtering.py  # include/exclude/--all/default patterns + arg parsing
│   └── test_stream_to_r2.py  # resume/retry regression suite
├── requirements.txt       # runtime deps (boto3, huggingface_hub, requests)
├── requirements-dev.txt   # -r requirements.txt + pytest
└── .github/workflows/ci.yml
```

## Acceptance criteria

### Unit tests
- [ ] `normalize_repo_id`: bare id, full URL, `/tree/main` URL, `hf.co` short
      URL, scheme-less URL, dataset URL (switches repo_type), space URL,
      non-HF host rejected, unparseable path rejected
- [ ] File filtering: default patterns keep `*.gguf` / `*.safetensors` /
      `config.json` / `tokenizer*` and drop `README.md`, `generation_config.json`,
      `.gitattributes`; `--include` overrides defaults; `--all` disables
      filtering; `--exclude` removes matches
- [ ] Arg parsing: no-args default resolves to `DEFAULT_INCLUDE`; `--all` wins
- [ ] `validate_env`: exits with error when R2 vars are missing

### Regression tests (stream_to_r2)
- [ ] Happy path: multi-part file assembles byte-identical in fake R2,
      multipart completed, correct part numbering
- [ ] Small file (< one chunk) uploads as a single final part
- [ ] One disconnect mid-stream → reconnects with `Range: bytes=<committed>-`,
      final bytes identical, no duplicate or missing data
- [ ] Multiple disconnects → still byte-identical
- [ ] Retry budget resets after progress (a flaky connection that always
      commits at least one part eventually succeeds, regardless of drop count)
- [ ] No progress + retries exhausted → raises, multipart upload aborted,
      exactly MAX_RETRIES+1 connection attempts
- [ ] Resume response without HTTP 206 → raises, multipart aborted
- [ ] Failure before any part uploads → no orphaned multipart upload

### CI
- [ ] GitHub Actions runs pytest on every push and PR to main
- [ ] Matrix: Python 3.11, 3.12, 3.13, 3.14
- [ ] Suite passes locally and in CI

## Code style

Match the existing script: plain Python, stdlib-first, no type-annotation
ceremony. Tests use plain pytest (no unittest classes), fakes over mock-magic
where a fake is clearer.

## Testing strategy

- `conftest.py` sets dummy R2 env vars, then imports `hf_to_r2` via
  `importlib` (module reads env at import time).
- `FakeResponse` simulates `requests.get` streaming with programmable
  disconnect points; `FakeR2Client` records multipart parts in memory.
- `time.sleep` is patched to a no-op so backoff tests run instantly.
- Regression tests assert on reassembled bytes, not implementation details.

## Boundaries

- **Always:** keep tests network-free and deterministic; keep them fast (<5s).
- **Ask first:** any change to `hf_to_r2.py` production code.
- **Never:** hit real R2/HF in tests; commit credentials; cut a release from
  a red build.
