# ── Cloudflare R2 config ──────────────────────────────────────────────────────
# Fill in your own values — see README for how to create R2 API credentials.
export R2_ENDPOINT="https://<ACCOUNT_ID>.r2.cloudflarestorage.com"
export R2_ACCESS_KEY_ID="your_access_key_id"
export R2_SECRET_ACCESS_KEY="your_secret_access_key"
export R2_BUCKET="your-bucket-name"
# export R2_UPLOAD_WORKERS=4   # parallel uploads, default 4

# ── HuggingFace token ─────────────────────────────────────────────────────────
# Required for full download speeds — unauthenticated requests are rate-limited.
# Get yours at https://huggingface.co/settings/tokens (read access is enough)
export HF_TOKEN="hf_your_token_here"

export HF_TO_R2_SCRIPT="$HOME/.local/bin/hf_to_r2.py"
export HF_TO_R2_PYTHON="$HOME/.venvs/hf-to-r2/bin/python3"
alias python3-hf="$HF_TO_R2_PYTHON"

# ── hf-to-r2: stream HuggingFace model files directly to Cloudflare R2 ───────
# Usage:
#   hf-to-r2 Qwen/Qwen3-32B                              # default: *.gguf *.safetensors config.json tokenizer*
#   hf-to-r2 https://huggingface.co/Qwen/Qwen3-32B       # full URLs work too
#   hf-to-r2 Qwen/Qwen3-32B --all                        # every file in the repo
#   hf-to-r2 Qwen/Qwen3-32B --safetensors                # safetensors only
#   hf-to-r2 Qwen/Qwen3-32B --include "*.safetensors" "config.json"
#   hf-to-r2 Qwen/Qwen3-32B --prefix "backups/my-models/"
#   hf-to-r2 Qwen/Qwen3-32B --workers 8
function hf-to-r2() {
  if [[ $# -eq 0 ]]; then
    echo "Usage: hf-to-r2 <repo_id_or_url> [--all] [--safetensors] [--include PATTERN...] [--prefix PREFIX] [--workers N]"
    echo ""
    echo "Default include patterns: *.gguf *.safetensors config.json tokenizer*"
    echo ""
    echo "Examples:"
    echo "  hf-to-r2 Qwen/Qwen3-32B"
    echo "  hf-to-r2 https://huggingface.co/Qwen/Qwen3-32B"
    echo "  hf-to-r2 Qwen/Qwen3-32B --all"
    echo "  hf-to-r2 Qwen/Qwen3-32B --safetensors"
    echo "  hf-to-r2 mistralai/Mistral-7B-v0.1 --include '*.safetensors' 'config.json' 'tokenizer*'"
    echo "  hf-to-r2 Qwen/Qwen3-32B --prefix 'backups/qwen/'"
    return 1
  fi

  # Check dependencies
  local py="${HF_TO_R2_PYTHON:-$HOME/.venvs/hf-to-r2/bin/python3}"
  if [[ ! -x "$py" ]]; then
    echo "✗ venv python not found: $py"
    echo "  Create it with: python3 -m venv ~/.venvs/hf-to-r2 && ~/.venvs/hf-to-r2/bin/pip install boto3 huggingface_hub requests"
    return 1
  fi

  local missing_deps=()
  "$py" -c "import boto3" 2>/dev/null           || missing_deps+=("boto3")
  "$py" -c "import huggingface_hub" 2>/dev/null || missing_deps+=("huggingface_hub")
  "$py" -c "import requests" 2>/dev/null        || missing_deps+=("requests")

  if [[ ${#missing_deps[@]} -gt 0 ]]; then
    echo "✗ Missing Python dependencies: ${missing_deps[*]}"
    echo "  Install with: $py -m pip install ${missing_deps[*]}"
    return 1
  fi

  # Convenience: --safetensors expands to --include pattern
  local args=("$@")
  local expanded=()
  for arg in "${args[@]}"; do
    if [[ "$arg" == "--safetensors" ]]; then
      expanded+=("--include" "*.safetensors" "config.json" "tokenizer.json" "tokenizer_config.json" "generation_config.json" "special_tokens_map.json")
    else
      expanded+=("$arg")
    fi
  done

  "$py" "${HF_TO_R2_SCRIPT:-$HOME/.local/bin/hf_to_r2.py}" "${expanded[@]}"
}

# ── hf-r2-ls: list files in R2 bucket under a prefix ─────────────────────────
function hf-r2-ls() {
  local prefix="${1:-models/}"
  local py="${HF_TO_R2_PYTHON:-$HOME/.venvs/hf-to-r2/bin/python3}"
  # Quoted heredoc: the prefix is passed via env, never expanded into the code.
  HF_R2_LS_PREFIX="$prefix" "$py" - <<'EOF'
import boto3, os
from botocore.config import Config
client = boto3.client(
    "s3",
    endpoint_url=os.environ["R2_ENDPOINT"],
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    config=Config(signature_version="s3v4"),
    region_name="auto",
)
paginator = client.get_paginator("list_objects_v2")
total_size = 0
count = 0
for page in paginator.paginate(Bucket=os.environ["R2_BUCKET"], Prefix=os.environ.get("HF_R2_LS_PREFIX", "models/")):
    for obj in page.get("Contents", []):
        size_gb = obj["Size"] / 1024**3
        print(f"  {size_gb:6.2f} GB  {obj['Key']}")
        total_size += obj["Size"]
        count += 1
print(f"\n  {count} files · {total_size/1024**3:.2f} GB total")
EOF
}
