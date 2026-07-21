import pytest


@pytest.mark.parametrize("raw, expected_id, expected_type", [
    ("Qwen/Qwen3-32B", "Qwen/Qwen3-32B", "model"),
    ("Qwen/Qwen3-32B/", "Qwen/Qwen3-32B", "model"),
    ("https://huggingface.co/zai-org/GLM-5.2", "zai-org/GLM-5.2", "model"),
    ("https://huggingface.co/zai-org/GLM-5.2/tree/main", "zai-org/GLM-5.2", "model"),
    ("https://www.huggingface.co/foo/bar", "foo/bar", "model"),
    ("huggingface.co/foo/bar", "foo/bar", "model"),
    ("hf.co/foo/bar", "foo/bar", "model"),
    ("https://huggingface.co/datasets/user/my-dataset", "user/my-dataset", "dataset"),
    ("https://huggingface.co/spaces/user/my-space", "user/my-space", "space"),
])
def test_accepted_forms(mod, raw, expected_id, expected_type):
    assert mod.normalize_repo_id(raw, "model") == (expected_id, expected_type)


def test_explicit_repo_type_is_preserved_for_bare_ids(mod):
    assert mod.normalize_repo_id("user/my-dataset", "dataset") == ("user/my-dataset", "dataset")


@pytest.mark.parametrize("raw", [
    "https://example.com/foo/bar",       # not a HuggingFace host
    "https://huggingface.co/only-one",   # no repo name after the org
    "https://huggingface.co/datasets",   # section with no repo at all
])
def test_rejected_forms_exit(mod, raw):
    with pytest.raises(SystemExit):
        mod.normalize_repo_id(raw, "model")
