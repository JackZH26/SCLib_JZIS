#!/bin/zsh
# Bounded Mac operator entrypoint. Explicit database commands write only private proposals.
set -euo pipefail
umask 077
site_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
runtime_root="${MATERIALS_NER_RUNTIME_ROOT:-$(dirname -- "$site_root")/runtime}"
ner_python="${MATERIALS_NER_PYTHON:-$runtime_root/materials-ner-venv/bin/python}"
ner_state="${MATERIALS_NER_STATE_ROOT:-$runtime_root/materials-ner}"
codex_dir="/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS"
if [[ ! -x "$ner_python" ]]; then
  print -u2 "Materials NER Python is unavailable. See docs/reviews/materials-schema-ml-2026-10-21/MAC_NER_RUNBOOK.md."
  exit 1
fi
if [[ -x "$codex_dir/codex" ]]; then
  export PATH="$codex_dir:$PATH"
fi
export PYTHONPATH="$site_root/ingestion${PYTHONPATH:+:$PYTHONPATH}"
exec "$ner_python" -m ingestion.materials_ner --root "$ner_state" "$@"
