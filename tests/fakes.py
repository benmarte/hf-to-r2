"""Test doubles shared by conftest fixtures and tests.

Kept out of conftest.py so tests can import the classes directly without
relying on pytest's conftest import mechanics.
"""

import requests


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
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(f"{self.status_code} Client Error")
            error.response = self
            raise error

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
    `http_status` forces an HTTP error status on every connection.
    Records the Range offset of every connection in `request_offsets`.
    """

    def __init__(self, data, fail_after=None, range_support=True,
                 refuse_connection=False, http_status=None):
        self.data = data
        self.fail_after = list(fail_after or [])
        self.range_support = range_support
        self.refuse_connection = refuse_connection
        self.http_status = http_status
        self.request_offsets = []

    def get(self, url, headers=None, stream=True, timeout=None):
        start = 0
        if headers and "Range" in headers:
            start = int(headers["Range"].split("=")[1].rstrip("-"))
        self.request_offsets.append(start)
        if self.refuse_connection:
            raise requests.exceptions.ConnectionError("simulated refused connection")
        fail_after = self.fail_after.pop(0) if self.fail_after else None
        if self.http_status:
            status = self.http_status
        else:
            status = 206 if (start and self.range_support) else 200
        return FakeResponse(self.data, start if self.range_support else 0, fail_after, status)


class FakeR2Client:
    """In-memory stand-in for the boto3 S3 client surface hf_to_r2 uses."""

    class exceptions:
        class ClientError(Exception):
            pass

    def __init__(self, existing_keys=(), fail_upload_part_at=None,
                 abort_raises=False, head_object_error=None):
        self.existing_keys = set(existing_keys)
        self.fail_upload_part_at = fail_upload_part_at
        self.abort_raises = abort_raises
        self.head_object_error = head_object_error
        self.parts = {}
        self.uploads_created = 0
        self.completed = False
        self.completed_parts = None
        self.aborted = False

    def head_object(self, Bucket, Key):
        if self.head_object_error is not None:
            raise self.head_object_error
        if Key not in self.existing_keys:
            raise self.exceptions.ClientError(f"404: {Key}")
        return {}

    def create_multipart_upload(self, Bucket, Key, ContentType=None):
        self.uploads_created += 1
        return {"UploadId": f"upload-{self.uploads_created}"}

    def upload_part(self, Bucket, Key, UploadId, PartNumber, Body):
        if self.fail_upload_part_at is not None and PartNumber >= self.fail_upload_part_at:
            raise self.exceptions.ClientError("simulated R2 503 on upload_part")
        self.parts[PartNumber] = bytes(Body)
        return {"ETag": f"etag-{PartNumber}"}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        self.completed = True
        self.completed_parts = MultipartUpload["Parts"]

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted = True
        if self.abort_raises:
            raise self.exceptions.ClientError("simulated abort failure")

    def assembled(self):
        return b"".join(self.parts[n] for n in sorted(self.parts))
