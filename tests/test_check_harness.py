import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def harness():
    spec = importlib.util.spec_from_file_location("check_harness", ROOT / "scripts/check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_commands_use_current_python():
    steps = harness().commands("test-python")
    assert [name for name, _ in steps] == ["lint", "package", "tests"]
    assert all(command[0] == "test-python" for _, command in steps)
    assert all(command[0] not in {"gh", "hermes", "codex"} for _, command in steps)


@pytest.mark.parametrize("returncode", [0, 1, 5])
def test_step_retains_real_exit_code_and_utf8_log(tmp_path, returncode):
    module = harness()
    result = module.run_step(
        "sample",
        [sys.executable, "-c", f"print('Проверка'); raise SystemExit({returncode})"],
        tmp_path, tmp_path, 10,
    )
    assert result["returncode"] == returncode
    assert result["passed"] is (returncode == 0)
    assert "Проверка" in Path(result["log_path"]).read_text(encoding="utf-8")


def test_step_records_missing_executable(tmp_path):
    result = harness().run_step(
        "missing", [str(tmp_path / "missing-executable")], tmp_path, tmp_path, 10,
    )
    assert result["returncode"] == 127
    assert result["passed"] is False


def test_step_records_timeout(tmp_path):
    result = harness().run_step(
        "slow", [sys.executable, "-c", "import time; time.sleep(10)"],
        tmp_path, tmp_path, 0.05,
    )
    assert result["returncode"] == 124
    assert "Timeout" in result["error"]


def test_orchestration_reports_all_failures_and_keeps_unique_runs(tmp_path, monkeypatch):
    module = harness()
    seen = []

    def fake_step(name, command, root, folder, timeout):
        seen.append(name)
        return {"name": name, "returncode": 1 if name == "lint" else 0,
                "passed": name != "lint", "log_path": str(folder / f"{name}.log")}

    monkeypatch.setattr(module, "run_step", fake_step)
    monkeypatch.setattr(module, "git_snapshot", lambda root: {"available": False, "reason": "test"})
    report, path = module.run_checks(tmp_path, sys.executable, 10)
    assert seen == ["lint", "package", "tests"]
    assert report["passed"] is False
    assert report["git_state_changed"] is None
    assert json.loads(path.read_text(encoding="utf-8"))["passed"] is False
    _, second = module.run_checks(tmp_path, sys.executable, 10)
    assert second != path


def test_git_state_change_is_recorded(tmp_path, monkeypatch):
    module = harness()
    snapshots = iter([
        {"available": True, "commit": "a", "branch": "task", "status": ""},
        {"available": True, "commit": "a", "branch": "task", "status": " M file.py"},
    ])
    monkeypatch.setattr(module, "git_snapshot", lambda root: next(snapshots))
    monkeypatch.setattr(module, "run_step", lambda name, *args: {
        "name": name, "passed": True, "returncode": 0,
    })
    report, _ = module.run_checks(tmp_path, sys.executable, 10)
    assert report["git_state_changed"] is True


def test_list_does_not_run_checks_or_create_reports(monkeypatch, capsys):
    module = harness()
    monkeypatch.setattr(sys, "argv", ["check.py", "--list"])
    monkeypatch.setattr(module, "run_checks", lambda *args: pytest.fail("must not run"))
    assert module.main() == 0
    assert "lint:" in capsys.readouterr().out


def test_cli_failure_returns_nonzero(monkeypatch):
    module = harness()
    monkeypatch.setattr(sys, "argv", ["check.py"])
    monkeypatch.setattr(module, "run_checks", lambda *args: (
        {"passed": False, "git_before": {"available": False}, "git_state_changed": None},
        Path("report.json"),
    ))
    assert module.main() == 1


def test_cli_pass_returns_zero(monkeypatch):
    module = harness()
    monkeypatch.setattr(sys, "argv", ["check.py"])
    monkeypatch.setattr(module, "run_checks", lambda *args: (
        {"passed": True, "git_before": {"available": True}, "git_state_changed": False},
        Path("report.json"),
    ))
    assert module.main() == 0


def test_cli_infrastructure_error_returns_two(monkeypatch):
    module = harness()
    monkeypatch.setattr(sys, "argv", ["check.py"])
    def fail(*args):
        raise OSError("cannot write report")
    monkeypatch.setattr(module, "run_checks", fail)
    assert module.main() == 2


def test_git_snapshot_records_root_branch_commit_and_status(tmp_path, monkeypatch):
    module = harness()
    outputs = iter([str(tmp_path), "abc123", "task/test", " M file.py"])

    def fake_run(command, **kwargs):
        assert command[0] == "git"
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["check"] is False
        return SimpleNamespace(returncode=0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    snapshot = module.git_snapshot(tmp_path)
    assert snapshot["available"] is True
    assert snapshot["branch"] == "task/test"
    assert snapshot["commit"] == "abc123"


def test_git_snapshot_missing_git_is_explicit(tmp_path, monkeypatch):
    module = harness()

    def missing(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(module.subprocess, "run", missing)
    snapshot = module.git_snapshot(tmp_path)
    assert snapshot["available"] is False
    assert "git unavailable" in snapshot["reason"]


def test_ancestor_git_root_is_not_accepted(tmp_path, monkeypatch):
    module = harness()
    outputs = iter([str(tmp_path.parent), "abc123", "main", ""])
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=next(outputs), stderr="",
    ))
    snapshot = module.git_snapshot(tmp_path)
    assert snapshot["available"] is False
    assert "differs" in snapshot["reason"]
