import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def importer():
    spec = importlib.util.spec_from_file_location("import_issues", ROOT / "scripts/import_issues.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ids_are_exact_not_substrings():
    module = importer()
    assert module.task_id("[Р1.1] Task") == "Р1.1"
    assert module.task_id("[Р1.11] Task") == "Р1.11"
    assert module.task_id("prefix [Р1.1]") is None


def test_manifest_has_54_valid_unique_tasks():
    module = importer()
    assert len(module.load_rows()) == 54
    assert len(module.load_rows(["Р1.11", "Р2.10", "Р3.11", "Р5.9"])) == 4
    with pytest.raises(ValueError):
        module.load_rows(["Р9.99"])


def test_dry_run_is_offline():
    run = subprocess.run([
        sys.executable, str(ROOT / "scripts/import_issues.py"), "owner/repo",
        "--dry-run", "--only", "Р1.11", "Р2.10",
    ], capture_output=True, text=True, encoding="utf-8", check=True)
    assert "Planned: 2" in run.stdout
    assert "no network calls" in run.stdout


def test_repeat_skips_existing_and_update_backs_up(monkeypatch, tmp_path):
    module = importer()
    row = module.load_rows(["Р1.11"])[0]
    old = {"number": 17, "title": "[Р1.11] Old", "body": "Team notes", "state": "closed"}
    calls = []

    def fake_gh(*args):
        calls.append(args)
        return ""

    def fake_paginated(endpoint):
        if "/labels?" in endpoint:
            return [{"name": "task"}, {"name": row["labels"]}]
        if "/milestones?" in endpoint:
            return [{"title": row["milestone"]}]
        return [old]

    monkeypatch.setattr(module, "gh", fake_gh)
    monkeypatch.setattr(module, "paginated", fake_paginated)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.apply("owner/repo", [row], False)["skipped"] == 1
    assert not any(c[:2] == ("issue", "create") for c in calls)
    assert not any(c[:2] == ("issue", "edit") for c in calls)
    assert module.apply("owner/repo", [row], True)["updated"] == 1
    backups = list((tmp_path / "out/issue-backups").glob("*/*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["body"] == "Team notes"
    assert any(c[:2] == ("issue", "edit") for c in calls)


def test_api_failure_stops_import(monkeypatch):
    module = importer()
    def fail(*args):
        raise subprocess.CalledProcessError(1, "gh", stderr="permission denied")
    monkeypatch.setattr(module, "gh", fail)
    with pytest.raises(subprocess.CalledProcessError):
        module.apply("owner/repo", [], False)
