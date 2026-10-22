"""Run fixed local checks and retain evidence. Does not call agents or GitHub."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def commands(python: str) -> list[tuple[str, list[str]]]:
    return [
        ("lint", [python, "-m", "ruff", "check", "src", "scripts", "tests", "plugins"]),
        ("package", [python, "scripts/validate_package.py"]),
        ("tests", [python, "-m", "pytest", "-v"]),
    ]


def git_snapshot(root: Path) -> dict:
    result = {}
    for name, args in [
        ("root", ["rev-parse", "--show-toplevel"]),
        ("commit", ["rev-parse", "HEAD"]),
        ("branch", ["branch", "--show-current"]),
        ("status", ["status", "--porcelain"]),
    ]:
        try:
            run = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"available": False, "reason": str(error)}
        if run.returncode:
            return {"available": False, "reason": run.stderr.strip() or "Git returned nonzero"}
        result[name] = run.stdout.strip()
    # Do not mistake an ancestor repository for the intended project repository.
    if Path(result["root"]).resolve() != root.resolve():
        return {"available": False, "reason": "Git root differs from project root"}
    return {"available": True, **result}


def run_step(name: str, command: list[str], root: Path, folder: Path, timeout: int) -> dict:
    log = folder / f"{name}.log"
    start = time.monotonic()
    error = None
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    with log.open("wb") as stream:
        try:
            run = subprocess.run(
                command, cwd=root, env=env, stdout=stream,
                stderr=subprocess.STDOUT, timeout=timeout, check=False,
            )
            code = run.returncode
        except subprocess.TimeoutExpired:
            code, error = 124, f"Timeout after {timeout} seconds"
        except OSError as exception:
            code, error = 127, str(exception)
        if error:
            stream.write(("\nHARNESS ERROR: " + error + "\n").encode("utf-8"))
    return {
        "name": name,
        "command": command,
        "returncode": code,
        "passed": code == 0,
        "duration_seconds": round(time.monotonic() - start, 3),
        "log_path": str(log.resolve()),
        "error": error,
    }


def run_checks(root: Path, python: str, timeout: int) -> tuple[dict, Path]:
    started = datetime.now(UTC)
    run_id = f"{started.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex[:8]}"
    folder = root / "out/checks" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    before = git_snapshot(root)
    checks = []
    for name, command in commands(python):
        item = run_step(name, command, root, folder, timeout)
        checks.append(item)
        print(f"{name}: {'PASS' if item['passed'] else 'FAIL'} (exit {item['returncode']})")
    after = git_snapshot(root)
    passed = all(item["passed"] for item in checks)
    report = {
        "schema_version": "1",
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "project_root": str(root.resolve()),
        "python_executable": python,
        "python_version": sys.version,
        "git_before": before,
        "git_after": after,
        "git_state_changed": (
            before != after if before.get("available") and after.get("available") else None
        ),
        "checks": checks,
        "passed": passed,
        "scope": "Local configured checks only; not business acceptance or client delivery.",
    }
    target = folder / "report.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, target


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="Show commands only, offline, no writes")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.list:
        for name, command in commands(sys.executable):
            print(f"{name}: {subprocess.list2cmdline(command)}")
        return 0
    try:
        report, target = run_checks(ROOT, sys.executable, args.timeout_seconds)
    except (OSError, ValueError) as error:
        print(f"HARNESS ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Report: {target.resolve()}")
    if not report["git_before"].get("available"):
        print("NOTE: project Git state unavailable; this does not prove a clean branch.")
    if report["git_state_changed"]:
        print("WARNING: Git state changed during checks; inspect changes and re-run if needed.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
