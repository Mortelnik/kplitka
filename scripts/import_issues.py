"""Import prepared issues via gh. Dry-run is local and never contacts GitHub."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^\[(Р[1-5]\.\d+)\](?:\s|$)")


def task_id(title: str) -> str | None:
    match = ID.match(title)
    return match.group(1) if match else None


def load_rows(only: list[str] | None = None) -> list[dict]:
    with (ROOT / "issues/manifest.tsv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file, delimiter="\t"))
    seen = set()
    for row in rows:
        identifier = task_id(row["title"])
        if not identifier or identifier in seen:
            raise ValueError(f"Missing or duplicate task ID: {row['title']}")
        seen.add(identifier)
        source = (ROOT / "issues" / row["file"]).resolve()
        if source.parent != (ROOT / "issues").resolve() or not source.is_file():
            raise ValueError(f"Invalid body file: {row['file']}")
        row["id"] = identifier
        row["path"] = str(source)
    if only:
        unknown = set(only) - seen
        if unknown:
            raise ValueError(f"Unknown IDs: {sorted(unknown)}")
        rows = [row for row in rows if row["id"] in only]
    return rows


def gh(*args: str) -> str:
    completed = subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return completed.stdout


def paginated(endpoint: str) -> list[dict]:
    pages = json.loads(gh("api", "--paginate", "--slurp", endpoint))
    return [item for page in pages for item in page]


def apply(repo: str, rows: list[dict], update: bool) -> dict:
    gh("auth", "status")
    gh("repo", "view", repo)
    # Do not suppress auth/API failures or treat them as missing objects.
    labels = {item["name"] for item in paginated(f"repos/{repo}/labels?per_page=100")}
    milestones = {item["title"] for item in paginated(
        f"repos/{repo}/milestones?state=all&per_page=100"
    )}
    existing = {}
    for item in paginated(f"repos/{repo}/issues?state=all&per_page=100"):
        if "pull_request" in item:
            continue
        identifier = task_id(item["title"])
        if identifier:
            if identifier in existing:
                raise ValueError(f"Duplicate GitHub issues for {identifier}; resolve manually")
            existing[identifier] = item
    for label in sorted({"task"} | {row["labels"] for row in rows}):
        if label not in labels:
            gh("label", "create", label, "--repo", repo, "--color", "5319e7")
    for milestone in sorted({row["milestone"] for row in rows if row["milestone"]}):
        if milestone not in milestones:
            gh("api", f"repos/{repo}/milestones", "-f", f"title={milestone}")
    totals = {"created": 0, "updated": 0, "skipped": 0}
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = ROOT / "out/issue-backups" / stamp
    for row in rows:
        previous = existing.get(row["id"])
        if previous and not update:
            totals["skipped"] += 1
            continue
        if previous:
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"{previous['number']}.json").write_text(
                json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            command = [
                "issue", "edit", str(previous["number"]), "--repo", repo,
                "--title", row["title"], "--body-file", row["path"],
                "--add-label", f"{row['labels']},task",
            ]
        else:
            command = [
                "issue", "create", "--repo", repo, "--title", row["title"],
                "--body-file", row["path"], "--label", f"{row['labels']},task",
            ]
        if row["milestone"]:
            command += ["--milestone", row["milestone"]]
        print(gh(*command).strip())
        totals["updated" if previous else "created"] += 1
    return totals


def main() -> int:
    # JSON and Cyrillic task IDs use UTF-8 even in redirected Windows output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="OWNER/REPO")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--update-existing", action="store_true",
                        help="Replace selected issue title/body, backing up prior state locally")
    parser.add_argument("--only", nargs="+", help="Stable task IDs, e.g. Р1.11 Р2.10")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
            raise ValueError("Expected OWNER/REPO")
        rows = load_rows(args.only)
        if args.dry_run:
            print("LOCAL DRY RUN: no network calls; existing GitHub state is not checked.")
            for row in rows:
                action = "create-or-update" if args.update_existing else "create-if-missing"
                print(f"{action}: {row['title']} | {row['milestone'] or 'no milestone'}")
            print(f"Planned: {len(rows)}")
            return 0
        if not shutil.which("gh"):
            raise ValueError("GitHub CLI not found. Install gh and run gh auth login.")
        print(json.dumps(apply(args.repo, rows, args.update_existing)))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        details = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(f"ERROR: {details}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
