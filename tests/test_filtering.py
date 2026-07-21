"""Regression tests for file filtering, --include/--all/--exclude resolution,
and env validation, run through main() with the HF API and R2 faked out."""

import sys

import pytest

from conftest import FakeR2Client

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


@pytest.fixture
def run_main(mod, monkeypatch):
    """Run mod.main() with the given CLI args; return (uploaded r2 keys, client)."""

    def run(*argv, existing_keys=()):
        uploaded = []
        client = FakeR2Client(existing_keys=existing_keys)
        monkeypatch.setattr(mod, "HfApi", FakeApi)
        monkeypatch.setattr(mod, "make_r2_client", lambda: client)
        monkeypatch.setattr(mod, "stream_to_r2",
                            lambda cl, url, r2_key, filename, token=None: uploaded.append(r2_key))
        monkeypatch.setattr(sys, "argv", ["hf_to_r2.py", "user/test-model", *argv])
        mod.main()
        return uploaded, client

    return run


def strip_prefix(keys):
    return {k.removeprefix("models/user--test-model/") for k in keys}


def test_default_include_patterns(run_main):
    uploaded, _ = run_main()
    assert strip_prefix(uploaded) == DEFAULT_KEPT


def test_all_flag_uploads_everything(run_main):
    uploaded, _ = run_main("--all")
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


@pytest.mark.parametrize("var", ["R2_ENDPOINT", "R2_ACCESS_KEY_ID",
                                 "R2_SECRET_ACCESS_KEY", "R2_BUCKET"])
def test_validate_env_exits_when_var_missing(mod, monkeypatch, var):
    monkeypatch.delenv(var)
    with pytest.raises(SystemExit) as excinfo:
        mod.validate_env()
    assert excinfo.value.code == 1
