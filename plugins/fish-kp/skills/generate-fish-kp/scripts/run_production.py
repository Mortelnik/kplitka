"""Delegate JSON execution to the installed or explicitly located project runtime."""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime-root", type=Path)
    args, remaining = parser.parse_known_args()
    try:
        if args.runtime_root is not None:
            source = args.runtime_root.resolve() / "src"
            if not (source / "kp_plugin/production.py").is_file():
                raise ValueError("runtime-root must contain src/kp_plugin/production.py")
            sys.path.insert(0, str(source))
        from kp_plugin.production import main as run
    except (ImportError, ValueError) as error:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "error": str(error)},
                         ensure_ascii=False))
        return 2
    return run(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
