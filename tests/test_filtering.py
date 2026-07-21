"""Regression tests for file filtering, --include/--all/--exclude resolution,
env validation, and main()'s summary accounting, with the HF API and R2 faked."""

import re
import sys

import pytest

from fakes import FakeR2Client

REPO_FILES = [
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "model.gguf",
    "subdir/nested.gguf",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "tokenizer.model",
    "generation_config.json",
    "README.md",
    ".gitattributes",
]

DEFAULT_KEPT = {
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "model.gguf",
    "subdir/nested.gguf",  # patterns match on basename, so nested files count
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "tokenizer.model",
}


class FakeApi:
    def __init__(self, token=None):
        self.token = token

    def list_repo_files(self, repo_id, repo_type="model"):
        return list(REPO_FILES)


class BrokenApi(FakeApi):
    def list_repo_files(self, repo_id, repo_type="model"):
        raise RuntimeError("401: token required for gated model")


@pytest.fixture
def run_main(mod, monkeypatch):
    """Run mod.main() with the given CLI args; return (uploaded r2 keys, client).

    Files whose basename is in `fail_files` make the faked stream_to_r2 raise,
    exercising main()'s per-file error accounting.
    """

    def run(*argv, existing_keys=(), fail_files=(), api_cls=FakeApi):
        uploaded = []
        client = FakeR2Client(existing_keys=existing_keys)

        def fake_stream(cl, url, r2_key, filename, token=None):
            if filename in fail_files:
                raise RuntimeError(f"simulated stream failure: {filename}")
            uploaded.append(r2_key)

        monkeypatch.setattr(mod, "HfApi", api_cls)
        monkeypatch.setattr(mod, "make_r2_client", lambda: client)
        monkeypatch.setattr(mod, "stream_to_r2", fake_stream)
        monkeypatch.setattr(sys, "argv", ["hf_to_r2.py", "user/test-model", *argv])
        mod.main()
        return uploaded, client

    return run


def strip_prefix(keys):
    return {k.removeprefix("models/user--test-model/") for k in keys}


def plain(text):
    """Strip ANSI color codes so summary lines can be asserted on."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_default_include_patterns(run_main):
    uploaded, _ = run_main()
    assert strip_prefix(uploaded) == DEFAULT_KEPT


def test_all_flag_uploads_everything(run_main):
    uploaded, _ = run_main("--all")
    assert strip_prefix(uploaded) == set(REPO_FILES)


def test_all_wins_over_include(run_main):
    uploaded, _ = run_main("--all", "--include", "*.json")
    assert strip_prefix(uploaded) == set(REPO_FILES)


def test_include_overrides_defaults(run_main):
    uploaded, _ = run_main("--include", "*.json")
    assert strip_prefix(uploaded) == {"config.json", "tokenizer.json",
                                      "tokenizer_config.json", "generation_config.json"}


def test_exclude_applies_on_top_of_defaults(run_main):
    uploaded, _ = run_main("--exclude", "*.gguf")
    assert strip_prefix(uploaded) == DEFAULT_KEPT - {"model.gguf", "subdir/nested.gguf"}


def test_no_matches_exits_cleanly(run_main):
    with pytest.raises(SystemExit) as excinfo:
        run_main("--include", "*.nonexistent")
    assert excinfo.value.code == 0


def test_existing_files_are_skipped(run_main):
    uploaded, _ = run_main(existing_keys={"models/user--test-model/config.json"})
    assert strip_prefix(uploaded) == DEFAULT_KEPT - {"config.json"}


def test_custom_prefix(run_main):
    uploaded, _ = run_main("--prefix", "backups/llms/", "--include", "config.json")
    assert uploaded == ["backups/llms/config.json"]


def test_default_prefix_uses_repo_name(run_main):
    uploaded, _ = run_main("--include", "config.json")
    assert uploaded == ["models/user--test-model/config.json"]


def test_stream_failures_are_counted(run_main, capsys):
    uploaded, _ = run_main(fail_files={"model.gguf", "config.json"})
    out = plain(capsys.readouterr().out)
    assert strip_prefix(uploaded) == DEFAULT_KEPT - {"model.gguf", "config.json"}
    assert "uploaded : 6" in out
    assert "failed   : 2" in out


def test_concurrent_summary_counts_are_accurate(run_main, capsys):
    # 4 workers, mixed outcomes: 1 pre-existing skip, 2 failures, 5 uploads.
    uploaded, _ = run_main(
        "--workers", "4",
        existing_keys={"models/user--test-model/tokenizer.json"},
        fail_files={"model.gguf", "nested.gguf"},  # matched by basename
    )
    out = plain(capsys.readouterr().out)
    assert len(uploaded) == 5
    assert "uploaded : 5" in out
    assert "skipped  : 1" in out
    assert "failed   : 2" in out


def test_repo_listing_failure_exits_with_error(run_main):
    with pytest.raises(SystemExit) as excinfo:
        run_main(api_cls=BrokenApi)
    assert excinfo.value.code == 1


def test_file_exists_generic_error_treated_as_missing(mod):
    # If the exists-check itself blows up (endpoint unreachable), the file is
    # treated as absent and re-uploaded rather than crashing the run.
    client = FakeR2Client(head_object_error=RuntimeError("endpoint unreachable"))
    assert mod.file_exists_in_r2(client, "models/x/config.json") is False


@pytest.mark.parametrize("var", ["R2_ENDPOINT", "R2_ACCESS_KEY_ID",
                                 "R2_SECRET_ACCESS_KEY", "R2_BUCKET"])
def test_validate_env_exits_when_var_missing(mod, monkeypatch, var):
    monkeypatch.delenv(var)
    with pytest.raises(SystemExit) as excinfo:
        mod.validate_env()
    assert excinfo.value.code == 1
