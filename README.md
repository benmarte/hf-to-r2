# hf-to-r2

Stream HuggingFace model files directly to Cloudflare R2 storage — no local disk usage. Files are chunked and piped from HuggingFace straight to R2 via multipart upload.

Useful for backing up safetensor files, datasets, or any HuggingFace repo to your own cloud storage without needing hundreds of GB of local disk space.

---

## Requirements

- Python 3.8+
- A Cloudflare R2 bucket with API credentials
- A HuggingFace account (optional — only needed for gated/private models)

---

## Installation

### 1. Clone or download

```bash
# clone the repo
git clone https://github.com/benmarte/hf-to-r2
cd hf-to-r2

# or just download the two files manually
curl -O https://raw.githubusercontent.com/benmarte/hf-to-r2/main/hf_to_r2.py
curl -O https://raw.githubusercontent.com/benmarte/hf-to-r2/main/hf_r2_zshrc.zsh
```

### 2. Install the Python script

```bash
mkdir -p ~/.local/bin
cp hf_to_r2.py ~/.local/bin/hf_to_r2.py
chmod +x ~/.local/bin/hf_to_r2.py
```

### 3. Create the virtual environment

The shell functions run the script through a dedicated venv at `~/.venvs/hf-to-r2`:

```bash
python3 -m venv ~/.venvs/hf-to-r2
~/.venvs/hf-to-r2/bin/pip install boto3 huggingface_hub requests
```

> If you'd rather use a different Python (another venv, conda, system Python with the
> packages installed), point the functions at it:
> ```zsh
> export HF_TO_R2_PYTHON="/path/to/your/python3"
> ```

### 4. Add the zsh functions to your shell config

Append the contents of `hf_r2_zshrc.zsh` to your `~/.zshrc`:

```bash
cat hf_r2_zshrc.zsh >> ~/.zshrc
```

Then open `~/.zshrc` and fill in your R2 credentials (see [Configuration](#configuration) below).

Reload your shell:

```bash
source ~/.zshrc
```

> **Bash users:** the functions work in bash too. Append to `~/.bashrc` instead and reload with `source ~/.bashrc`.

---

## Configuration

`hf_r2_zshrc.zsh` ships with placeholder values. Open your shell config and replace them with your own:

```zsh
export R2_ENDPOINT="https://<ACCOUNT_ID>.r2.cloudflarestorage.com"
export R2_ACCESS_KEY_ID="your_access_key"
export R2_SECRET_ACCESS_KEY="your_secret"
export R2_BUCKET="your-bucket-name"
```

> **Never commit real credentials.** If you keep this file in a dotfiles repo, put the
> `export` lines in a separate untracked file (e.g. `~/.r2-secrets.zsh`) and source it.

### Getting your Cloudflare R2 credentials

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) → **R2** → your bucket
2. Click **Manage R2 API Tokens** → **Create API Token**
3. Give it **Object Read & Write** permissions scoped to your bucket
4. Copy the **Access Key ID** and **Secret Access Key**
5. Your account ID is in the URL: `dash.cloudflare.com/<ACCOUNT_ID>/r2`

### HuggingFace token (strongly recommended)

```zsh
export HF_TOKEN="hf_your_token_here"
```

Get your token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) — read access is enough.

Without a token, HuggingFace rate-limits unauthenticated requests and download speeds will be significantly slower. A free HuggingFace account is all you need. A token is also required for gated models (Llama, Gemma, etc.) where you've accepted the license on the HuggingFace website.

### Optional: custom script path

If you placed `hf_to_r2.py` somewhere other than `~/.local/bin/`:

```zsh
export HF_TO_R2_SCRIPT="/path/to/hf_to_r2.py"
```

### Optional: parallel upload workers

```zsh
export R2_UPLOAD_WORKERS=8   # default is 4
```

---

## Usage

### Basic

```bash
# upload all files in a repo
hf-to-r2 Qwen/Qwen3-32B

# full HuggingFace URLs work too — just paste from your browser
hf-to-r2 https://huggingface.co/Qwen/Qwen3-32B
hf-to-r2 https://huggingface.co/Qwen/Qwen3-32B/tree/main

# upload safetensors + config files only (recommended for model backups)
hf-to-r2 Qwen/Qwen3-32B --safetensors
```

### Filter files

```bash
# include specific patterns
hf-to-r2 Qwen/Qwen3-32B --include "*.safetensors" "config.json" "tokenizer*"

# exclude patterns
hf-to-r2 Qwen/Qwen3-32B --exclude "*.bin" "flax_model*"
```

### Custom R2 prefix

By default files land at `models/<repo-name>/` in your bucket. Override with `--prefix`:

```bash
hf-to-r2 Qwen/Qwen3-32B --prefix "backups/llms/qwen/"
```

### Parallel workers

```bash
# faster uploads on a good connection
hf-to-r2 Qwen/Qwen3-32B --safetensors --workers 8
```

### Datasets and Spaces

```bash
hf-to-r2 username/my-dataset --repo-type dataset
hf-to-r2 username/my-space --repo-type space

# dataset/space URLs set the repo type automatically
hf-to-r2 https://huggingface.co/datasets/username/my-dataset
```

### List files in R2

```bash
# list everything under models/
hf-r2-ls

# list a specific model
hf-r2-ls models/Qwen--Qwen3-32B/
```

---

## How it works

1. The HuggingFace API lists all files in the repo
2. Files are filtered by your include/exclude patterns
3. Each file is streamed from HuggingFace in 8 MB chunks
4. Chunks are uploaded to R2 via S3 multipart upload
5. Nothing is written to local disk

Files already present in R2 are skipped automatically, so re-running the command is safe and acts as a resume.

---

## R2 file layout

```
your-bucket/
└── models/
    └── Qwen--Qwen3-32B/
        ├── config.json
        ├── tokenizer.json
        ├── model-00001-of-00008.safetensors
        ├── model-00002-of-00008.safetensors
        └── ...
```

Slashes in the repo ID (`Qwen/Qwen3-32B`) are replaced with `--` in the R2 prefix to avoid ambiguity.

---

## Troubleshooting

**`Missing env vars` error**
Make sure you've set all four R2 environment variables and reloaded your shell (`source ~/.zshrc`).

**`venv python not found` error**
The venv at `~/.venvs/hf-to-r2` doesn't exist yet — create it (see [Installation](#3-create-the-virtual-environment)), or set `HF_TO_R2_PYTHON` to a Python that has the dependencies installed.

**`ModuleNotFoundError` / `Missing Python dependencies`**
Run `~/.venvs/hf-to-r2/bin/pip install boto3 huggingface_hub requests` and try again.

**`403 Forbidden` from HuggingFace**
The model requires a HuggingFace token. Set `HF_TOKEN` in your shell config and accept the model's license on the HuggingFace website first.

**`403 Forbidden` from R2**
Check that your API token has **Object Write** permission and is scoped to the correct bucket.

**Upload stalls on a large file**
Try reducing `--workers` to 2. High parallelism on very large shards can hit R2 rate limits.

---

## License

MIT
