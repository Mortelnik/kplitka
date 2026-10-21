"""Regression coverage for Windows locales that default to cp1251."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_validator_reads_utf8_even_if_default_is_cp1251(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "validate_package", ROOT / "scripts/validate_package.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = Path.read_text

    def windows_default(path, encoding=None, errors=None, **kwargs):
        return original(path, encoding=encoding or "cp1251", errors=errors, **kwargs)

    monkeypatch.setattr(Path, "read_text", windows_default)
    module.validate(ROOT)


def test_smoke_stdout_handles_cyrillic_paths_under_cp1251(tmp_path):
    skill = ROOT / "plugins/fish-kp/skills/generate-fish-kp"
    run = subprocess.run([
        sys.executable, str(skill / "scripts/smoke_docx.py"),
        "--input", str(skill / "assets/smoke-input.json"),
        "--output-dir", str(tmp_path / "Проверка-документа"),
    ], env={**os.environ, "PYTHONIOENCODING": "cp1251"},
        capture_output=True, text=True, encoding="utf-8", check=True)
    payload = json.loads(run.stdout)
    assert "Проверка-документа" in payload["document_path"]
    assert Path(payload["document_path"]).exists()


def test_importer_stdout_is_utf8_under_cp1251():
    run = subprocess.run([
        sys.executable, str(ROOT / "scripts/import_issues.py"),
        "owner/repo", "--dry-run", "--only", "Р1.11",
    ], env={**os.environ, "PYTHONIOENCODING": "cp1251"},
        capture_output=True, text=True, encoding="utf-8", check=True)
    assert "Р1.11" in run.stdout
