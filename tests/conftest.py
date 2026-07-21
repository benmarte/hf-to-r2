"""Shared fixtures and fakes for the hf-to-r2 test suite.

hf_to_r2.py reads R2 env vars at import time, so dummy values are set here
before the module is loaded. No test touches the network or a real bucket.
"""

import importlib.util
import os
from pathlib import Path

import pytest
import requests

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


class FakeResponse:
    """Streams a slice of `data` starting at `start`; drops the connection
    after serving `fail_after` bytes if set."""

    def __init__(self, data, start, fail_after, status_code):
        self.data = data
        self.start = start
        self.fail_after = fail_after
        self.status_code = status_code
        self.headers = {
            "content-length": str(len(data) - start),
            "content-type": "application/octet-stream",
        }

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        served = 0
        pos = self.start
        while pos < len(self.data):
            chunk = self.data[pos:pos + chunk_size]
            if self.fail_after is not None and served + len(chunk) > self.fail_after:
                raise requests.exceptions.ChunkedEncodingError("simulated disconnect")
            served += len(chunk)
            pos += len(chunk)
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeHF:
    """Stands in for requests.get against a HuggingFace download URL.

    `fail_after` is a list of byte counts: connection N drops after serving
    that many bytes; connections beyond the list stream to completion.
    Records the Range offset of every connection in `request_offsets`.
    """

    def __init__(self, data, fail_after=None, range_support=True, refuse_connection=False):
        self.data = data
        self.fail_after = list(fail_after or [])
        self.range_support = range_support
        self.refuse_connection = refuse_connection
        self.request_offsets = []

    def get(self, url, headers=None, stream=True, timeout=None):
        start = 0
        if headers and "Range" in headers:
            start = int(headers["Range"].split("=")[1].rstrip("-"))
        self.request_offsets.append(start)
        if self.refuse_connection:
            raise requests.exceptions.ConnectionError("simulated refused connection")
        fail_after = self.fail_after.pop(0) if self.fail_after else None
        status = 206 if (start and self.range_support) else 200
        return FakeResponse(self.data, start if self.range_support else 0, fail_after, status)


class FakeR2Client:
    """In-memory stand-in for the boto3 S3 client surface hf_to_r2 uses."""

    class exceptions:
        class ClientError(Exception):
            pass

    def __init__(self, existing_keys=()):
        self.existing_keys = set(existing_keys)
        self.parts = {}
        self.uploads_created = 0
        self.completed = False
        self.completed_parts = None
        self.aborted = False

    def head_object(self, Bucket, Key):
        if Key not in self.existing_keys:
            raise self.exceptions.ClientError(f"404: {Key}")
        return {}

    def create_multipart_upload(self, Bucket, Key, ContentType=None):
        self.uploads_created += 1
        return {"UploadId": f"upload-{self.uploads_created}"}

    def upload_part(self, Bucket, Key, UploadId, PartNumber, Body):
        self.parts[PartNumber] = bytes(Body)
        return {"ETag": f"etag-{PartNumber}"}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        self.completed = True
        self.completed_parts = MultipartUpload["Parts"]

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted = True

    def assembled(self):
        return b"".join(self.parts[n] for n in sorted(self.parts))


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
