"""Read local worker readiness without revealing credentials or invoking extraction."""
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys


def diagnose(root):
    codex = shutil.which("codex")
    version, login = None, False
    if codex:
        result = subprocess.run([codex, "--version"], capture_output=True, text=True, timeout=15)
        version = result.stdout.strip() if result.returncode == 0 else None
        auth = subprocess.run([codex, "login", "status"], capture_output=True, text=True, timeout=15)
        login = auth.returncode == 0
    return {
        "schema": "materials-ner-local-readiness/1",
        "system": platform.system(), "architecture": platform.machine(),
        "python": sys.version.split()[0], "python_executable": sys.executable,
        "packages": {name: importlib.metadata.version(name) for name in
                     ("pydantic", "tiktoken", "pypdf", "httpx", "google-cloud-storage")},
        "state_root": str(root), "available_disk_bytes": shutil.disk_usage(root).free,
        "codex_executable": codex, "codex_version": version, "codex_login_available": login,
        "responses_api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "responses_api_verified": False, "harvest_article_api_called": False,
        "scientific_acceptance": False,
    }
