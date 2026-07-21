#!/usr/bin/env python3
"""
hf-to-r2: Stream HuggingFace model files directly to Cloudflare R2.
No local disk usage — chunks stream from HF → R2 via multipart upload.

Usage (called by zsh function, not directly):
  hf-to-r2 <repo_id> [--include "*.safetensors"] [--prefix "models/"]
"""

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
from huggingface_hub import HfApi, hf_hub_url
from huggingface_hub.utils import build_hf_headers
import requests

# ── Config from env ────────────────────────────────────────────────────────────
R2_ENDPOINT    = os.environ.get("R2_ENDPOINT")       # https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_ACCESS_KEY  = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_KEY  = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET      = os.environ.get("R2_BUCKET")
HF_TOKEN       = os.environ.get("HF_TOKEN")          # optional, needed for gated models
CHUNK_SIZE     = 8 * 1024 * 1024                      # 8 MB chunks for multipart
MAX_WORKERS    = int(os.environ.get("R2_UPLOAD_WORKERS", "4"))
MAX_RETRIES    = int(os.environ.get("HF_DOWNLOAD_RETRIES", "8"))
RETRY_BACKOFF  = 2                                    # seconds, doubles per attempt (capped at 60s)

DEFAULT_INCLUDE = ["*.gguf", "*.safetensors", "config.json", "tokenizer*"]

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RED    = "\033[31m"
DIM    = "\033[2m"

def log(msg, color=RESET):       print(f"{color}{msg}{RESET}", flush=True)
def ok(msg):                     log(f"  ✓ {msg}", GREEN)
def info(msg):                   log(f"  · {msg}", CYAN)
def warn(msg):                   log(f"  ⚠ {msg}", YELLOW)
def err(msg):                    log(f"  ✗ {msg}", RED); sys.exit(1)


def normalize_repo_id(raw, repo_type):
    """Accept a bare repo id or a full huggingface.co URL.

    Handles forms like:
      zai-org/GLM-5.2
      https://huggingface.co/zai-org/GLM-5.2
      https://huggingface.co/zai-org/GLM-5.2/tree/main
      https://huggingface.co/datasets/foo/bar  (switches repo_type)
    """
    from urllib.parse import urlparse

    if "://" not in raw and not raw.startswith(("huggingface.co/", "hf.co/")):
        return raw.strip("/"), repo_type

    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    host = parsed.netloc.lower()
    if host not in ("huggingface.co", "www.huggingface.co", "hf.co"):
        err(f"Not a HuggingFace URL: {raw}")

    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[0] in ("datasets", "spaces"):
        repo_type = "dataset" if parts[0] == "datasets" else "space"
        parts = parts[1:]
    if len(parts) < 2:
        err(f"Could not parse a repo id from URL: {raw}")

    return "/".join(parts[:2]), repo_type


def validate_env():
    missing = [v for v in ["R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
               if not os.environ.get(v)]
    if missing:
        err(f"Missing env vars: {', '.join(missing)}\nSet them in your zshrc R2 config block.")

    if not os.environ.get("HF_TOKEN"):
        warn("HF_TOKEN is not set — unauthenticated requests are rate-limited and will be slow.")
        warn("Get a free token at https://huggingface.co/settings/tokens (read access is enough)\n")


def make_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 5, "mode": "adaptive"},
        ),
        region_name="auto",
    )


def file_exists_in_r2(client, key):
    try:
        client.head_object(Bucket=R2_BUCKET, Key=key)
        return True
    except client.exceptions.ClientError:
        return False
    except Exception:
        return False


def stream_to_r2(client, hf_url, r2_key, filename, token=None):
    """Stream a single file from HF directly to R2 via multipart upload.

    If the download connection drops, reconnects with an HTTP Range request
    starting at the last byte already committed to R2, so the multipart
    upload resumes instead of starting over.
    """
    base_headers = build_hf_headers(token=token) if token else {}

    upload_id = None
    parts = []
    part_num = 0
    committed = 0        # bytes safely uploaded to R2 as completed parts
    total_size = 0
    attempt = 0

    def upload_part(body):
        nonlocal part_num, committed
        part_num += 1
        part = client.upload_part(
            Bucket=R2_BUCKET,
            Key=r2_key,
            UploadId=upload_id,
            PartNumber=part_num,
            Body=body,
        )
        parts.append({"PartNumber": part_num, "ETag": part["ETag"]})
        committed += len(body)

    try:
        while True:
            headers = dict(base_headers)
            if committed:
                headers["Range"] = f"bytes={committed}-"
            try:
                with requests.get(hf_url, headers=headers, stream=True, timeout=(30, 60)) as resp:
                    resp.raise_for_status()
                    if committed and resp.status_code != 206:
                        # Server ignored the Range header — a full-body retry would
                        # corrupt the upload, so bail out.
                        raise RuntimeError("server does not support resume (no partial content)")
                    if not total_size:
                        total_size = int(resp.headers.get("content-length", 0))

                    # Use multipart upload — required for files > 5 GB, better for all large files
                    if upload_id is None:
                        mpu = client.create_multipart_upload(
                            Bucket=R2_BUCKET,
                            Key=r2_key,
                            ContentType=resp.headers.get("content-type", "application/octet-stream"),
                        )
                        upload_id = mpu["UploadId"]

                    buffer = b""
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        buffer += chunk

                        # Upload when buffer hits chunk size
                        if len(buffer) >= CHUNK_SIZE:
                            upload_part(buffer)
                            buffer = b""
                            attempt = 0  # progress made — reset the retry budget

                            if total_size:
                                pct = (committed / total_size) * 100
                                mb = committed / 1024 / 1024
                                total_mb = total_size / 1024 / 1024
                                print(f"\r  {DIM}↑ {filename}: {mb:.0f} / {total_mb:.0f} MB ({pct:.1f}%){RESET}",
                                      end="", flush=True)

                    # Upload remaining buffer as final part
                    if buffer:
                        upload_part(buffer)

                    # Complete the multipart upload
                    client.complete_multipart_upload(
                        Bucket=R2_BUCKET,
                        Key=r2_key,
                        UploadId=upload_id,
                        MultipartUpload={"Parts": parts},
                    )
                    print()  # newline after progress
                    return True

            except requests.exceptions.RequestException as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise
                wait = min(RETRY_BACKOFF * (2 ** (attempt - 1)), 60)
                print()  # move off the progress line
                warn(f"{filename}: connection lost ({type(e).__name__}), "
                     f"retry {attempt}/{MAX_RETRIES} in {wait}s "
                     f"(resuming at {committed / 1024 / 1024:.0f} MB)")
                time.sleep(wait)

    except Exception as e:
        # Abort the multipart upload on failure to avoid orphaned parts
        if upload_id is not None:
            try:
                client.abort_multipart_upload(
                    Bucket=R2_BUCKET,
                    Key=r2_key,
                    UploadId=upload_id,
                )
            except Exception:
                pass
        raise e


def match_patterns(filename, patterns):
    """Simple glob-style pattern matching."""
    if not patterns:
        return True
    import fnmatch
    return any(fnmatch.fnmatch(filename, p) for p in patterns)


def main():
    parser = argparse.ArgumentParser(description="Stream HF model files to Cloudflare R2")
    parser.add_argument("repo_id", help="HuggingFace repo ID or URL (e.g. Qwen/Qwen3-32B or https://huggingface.co/Qwen/Qwen3-32B)")
    parser.add_argument("--include", nargs="*", default=None, metavar="PATTERN",
                        help=f"Glob patterns to include (default: {' '.join(DEFAULT_INCLUDE)})")
    parser.add_argument("--all", action="store_true",
                        help="Upload every file in the repo (ignore the default include patterns)")
    parser.add_argument("--exclude", nargs="*", default=[], metavar="PATTERN",
                        help="Glob patterns to exclude")
    parser.add_argument("--prefix", default="", metavar="PREFIX",
                        help="R2 key prefix (e.g. 'models/') — defaults to repo name")
    parser.add_argument("--repo-type", default="model", choices=["model", "dataset", "space"])
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="Skip files already in R2 (default: true)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"Parallel upload workers (default: {MAX_WORKERS})")
    args = parser.parse_args()

    args.repo_id, args.repo_type = normalize_repo_id(args.repo_id, args.repo_type)

    if args.all:
        args.include = []
    elif args.include is None:
        args.include = DEFAULT_INCLUDE

    validate_env()

    # Determine R2 prefix
    repo_name = args.repo_id.replace("/", "--")
    prefix = args.prefix.rstrip("/") + "/" if args.prefix else f"models/{repo_name}/"

    log(f"\n{BOLD}🐦 hf-to-r2{RESET}")
    info(f"repo     : {args.repo_id}")
    info(f"bucket   : {R2_BUCKET}")
    info(f"prefix   : {prefix}")
    info(f"workers  : {args.workers}")
    info(f"include  : {args.include if args.include else 'all files'}")
    print()

    # List files in the HF repo
    api = HfApi(token=HF_TOKEN)
    try:
        files = api.list_repo_files(args.repo_id, repo_type=args.repo_type)
        files = list(files)
    except Exception as e:
        err(f"Could not list repo files: {e}")

    # Filter by include/exclude patterns
    import fnmatch
    filtered = []
    for f in files:
        fname = os.path.basename(f)
        if args.include and not any(fnmatch.fnmatch(fname, p) for p in args.include):
            continue
        if args.exclude and any(fnmatch.fnmatch(fname, p) for p in args.exclude):
            continue
        filtered.append(f)

    if not filtered:
        warn("No files matched the filter criteria.")
        sys.exit(0)

    info(f"Found {len(filtered)} file(s) to upload\n")

    client = make_r2_client()
    lock = threading.Lock()
    results = {"ok": 0, "skipped": 0, "failed": 0}

    def process_file(hf_path):
        filename = os.path.basename(hf_path)
        r2_key = prefix + hf_path  # preserve subdirectory structure

        # Check if already exists
        if args.skip_existing and file_exists_in_r2(client, r2_key):
            with lock:
                results["skipped"] += 1
            warn(f"skip (exists): {filename}")
            return

        url = hf_hub_url(args.repo_id, hf_path, repo_type=args.repo_type)
        info(f"uploading: {filename}")

        try:
            stream_to_r2(client, url, r2_key, filename, token=HF_TOKEN)
            with lock:
                results["ok"] += 1
            ok(f"done: {filename} → r2://{R2_BUCKET}/{r2_key}")
        except Exception as e:
            with lock:
                results["failed"] += 1
            log(f"  ✗ failed: {filename} — {e}", RED)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_file, f): f for f in filtered}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                log(f"  ✗ unexpected error: {e}", RED)

    print()
    log(f"{BOLD}Summary{RESET}")
    ok(f"uploaded : {results['ok']}")
    if results["skipped"]:
        warn(f"skipped  : {results['skipped']} (already in R2)")
    if results["failed"]:
        log(f"  ✗ failed   : {results['failed']}", RED)
    print()


if __name__ == "__main__":
    main()
