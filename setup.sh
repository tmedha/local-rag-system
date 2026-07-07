#!/usr/bin/env bash
#
# CloakedOracle bootstrap. Idempotent: safe to re-run.
# Sets up the Python environment and (if Ollama is present) pulls the LLM.
#
set -euo pipefail

cd "$(dirname "$0")"

# Model to pull; overridable via env or .env (LLM_MODEL=...).
LLM_MODEL="${LLM_MODEL:-llama3.2}"

say()  { printf '\033[1;35m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }

# 1) Virtualenv ------------------------------------------------------------
if [ ! -d ".venv" ]; then
  say "Creating virtualenv (.venv)…"
  python3 -m venv .venv
else
  say "Reusing existing .venv"
fi

# 2) Dependencies ----------------------------------------------------------
say "Installing Python dependencies (this can take a few minutes the first time)…"
./.venv/bin/python -m pip install --upgrade pip -q
./.venv/bin/pip install -r requirements.txt -q
say "Dependencies installed."

# 3) .env ------------------------------------------------------------------
if [ ! -f ".env" ]; then
  say "Creating .env from .env.example"
  cp .env.example .env
else
  say ".env already exists — leaving it untouched"
fi
# Pick up LLM_MODEL from .env if the user set it there.
if [ -f ".env" ]; then
  env_model="$(grep -E '^LLM_MODEL=' .env | tail -1 | cut -d= -f2- || true)"
  [ -n "${env_model:-}" ] && LLM_MODEL="$env_model"
fi

# 4) Ollama (guided, never force-installed) --------------------------------
if command -v ollama >/dev/null 2>&1; then
  say "Ollama found — pulling model '$LLM_MODEL'…"
  if ollama pull "$LLM_MODEL"; then
    say "Model '$LLM_MODEL' ready."
  else
    warn "Could not pull '$LLM_MODEL'. Is the Ollama server reachable? Try: ollama serve"
  fi
else
  warn "Ollama is not installed. CloakedOracle needs it for local generation."
  warn "  Install:  brew install ollama    (or download from https://ollama.com)"
  warn "  Then run: ollama serve  &&  ollama pull $LLM_MODEL"
fi

# 5) Next steps ------------------------------------------------------------
cat <<EOF

$(say "Setup complete.")

Next steps:
  1. Start Ollama in its own terminal:      ollama serve
  2. (if not already) pull the model:       ollama pull $LLM_MODEL
  3. Put documents in the ./documents vault (via the filesystem).
  4. Launch CloakedOracle:
       source .venv/bin/activate
       uvicorn app.main:app --reload
  5. Open http://localhost:8000
EOF
