"""Shared fixtures for the hf-to-r2 test suite.

hf_to_r2.py reads R2 env vars at import time, so dummy values are set here
before the module is loaded. No test touches the network or a real bucket.
Test doubles live in tests/fakes.py.
"""

import importlib.util
import os
from pathlib import Path

import pytest

from fakes import FakeHF, FakeR2Client

REPO_ROOT = Path(__file__).resolve().parent.parent

os.environ.setdefault("R2_ENDPOINT", "https://test.r2.cloudflarestorage.com")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test-access-key")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test-secret-key")
os.environ.setdefault("R2_BUCKET", "test-bucket")


@pytest.fixture(scope="session")
def mod():
    """The hf_to_r2 module, loaded once with test env vars in place."""
    spec = importlib.util.spec_from_file_location("hf_to_r2", REPO_ROOT / "hf_to_r2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_r2():
    return FakeR2Client


@pytest.fixture
def fake_hf():
    return FakeHF


@pytest.fixture
def stream(mod, monkeypatch):
    """Run mod.stream_to_r2 against a FakeHF and FakeR2Client with a tiny
    chunk size, no real sleeping, and a small retry budget."""
    monkeypatch.setattr(mod, "CHUNK_SIZE", 1024)
    monkeypatch.setattr(mod, "MAX_RETRIES", 3)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)

    def run(hf, client):
        monkeypatch.setattr(mod.requests, "get", hf.get)
        return mod.stream_to_r2(client, "https://fake/url", "models/test/file.bin", "file.bin")

    return run
