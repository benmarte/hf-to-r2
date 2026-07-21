"""Regression tests for stream_to_r2: multipart assembly, resume-on-disconnect
via HTTP Range, retry budget behavior, and multipart abort on failure.

CHUNK_SIZE is shrunk to 1 KB and MAX_RETRIES to 3 by the `stream` fixture.
"""

import pytest
import requests

DATA = bytes(range(256)) * 40  # 10,240 bytes = 10 parts at the 1 KB test chunk size


def test_happy_path_multipart(stream, fake_hf, fake_r2):
    hf, client = fake_hf(DATA), fake_r2()
    assert stream(hf, client) is True
    assert client.assembled() == DATA
    assert client.completed and not client.aborted
    assert sorted(client.parts) == list(range(1, 11))
    assert [p["PartNumber"] for p in client.completed_parts] == list(range(1, 11))
    assert hf.request_offsets == [0]


def test_small_file_single_part(stream, fake_hf, fake_r2):
    small = b"tiny config file"
    hf, client = fake_hf(small), fake_r2()
    assert stream(hf, client) is True
    assert client.assembled() == small
    assert client.completed and len(client.parts) == 1


def test_single_disconnect_resumes_at_committed_offset(stream, fake_hf, fake_r2):
    # Drops after 3,000 bytes: 2 full 1 KB parts committed, 952 bytes lost.
    hf, client = fake_hf(DATA, fail_after=[3000]), fake_r2()
    assert stream(hf, client) is True
    assert client.assembled() == DATA
    assert hf.request_offsets == [0, 2048]  # resume exactly at the committed boundary
    assert client.completed and not client.aborted


def test_multiple_disconnects_still_byte_identical(stream, fake_hf, fake_r2):
    hf, client = fake_hf(DATA, fail_after=[1500, 2500, 3000]), fake_r2()
    assert stream(hf, client) is True
    assert client.assembled() == DATA
    assert len(hf.request_offsets) == 4
    assert hf.request_offsets[0] == 0
    assert hf.request_offsets == sorted(hf.request_offsets)  # strictly forward progress


def test_retry_budget_resets_on_progress(stream, fake_hf, fake_r2):
    # Every connection commits one 1 KB part then drops. Nine drops far exceeds
    # MAX_RETRIES=3, but each commit resets the budget, so it must still finish.
    hf, client = fake_hf(DATA, fail_after=[1500] * 9), fake_r2()
    assert stream(hf, client) is True
    assert client.assembled() == DATA
    assert len(hf.request_offsets) == 10


def test_retries_exhausted_without_progress_aborts(stream, fake_hf, fake_r2):
    # Drops before the first part can ever be committed.
    hf, client = fake_hf(DATA, fail_after=[500] * 20), fake_r2()
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        stream(hf, client)
    assert len(hf.request_offsets) == 4  # initial attempt + MAX_RETRIES
    assert client.aborted and not client.completed


def test_resume_without_range_support_aborts(stream, fake_hf, fake_r2):
    # After a disconnect the server ignores Range and replies 200 from byte 0;
    # continuing would corrupt the object, so the upload must abort and raise.
    hf, client = fake_hf(DATA, fail_after=[3000], range_support=False), fake_r2()
    with pytest.raises(RuntimeError, match="resume"):
        stream(hf, client)
    assert client.aborted and not client.completed


def test_connection_refused_leaves_no_orphaned_upload(stream, fake_hf, fake_r2):
    # requests.get itself fails: no multipart upload was ever created,
    # so there must be nothing to abort (and no orphaned parts in R2).
    hf, client = fake_hf(DATA, refuse_connection=True), fake_r2()
    with pytest.raises(requests.exceptions.ConnectionError):
        stream(hf, client)
    assert client.uploads_created == 0
    assert not client.aborted and not client.completed
