"""Offline package integrity checks; not a host compatibility certification."""

import json
from pathlib import Path

import yaml


def validate(root: Path) -> None:
    plugin = root / "plugins/fish-kp"
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "fish-kp"
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert "skills" not in manifest, "Portable layout discovers skills/ by path"
    market = json.loads((root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert (root / market["plugins"][0]["source"]["path"]).resolve() == plugin.resolve()
    skill = plugin / "skills/generate-fish-kp"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load(text.split("---", 2)[1])
    assert metadata["name"] == skill.name
    assert isinstance(metadata["description"], str) and metadata["description"]
    assert "scripts/smoke_docx.py" in text
    for relative in [
        "scripts/smoke_docx.py", "scripts/requirements-smoke.txt",
        "references/runtime-check.md", "references/workflow.md",
        "assets/template_kp.docx", "assets/smoke-input.json",
    ]:
        assert (skill / relative).is_file(), relative
    print("Package paths and frontmatter OK; Kalitka AI runtime remains unverified.")


if __name__ == "__main__":
    validate(Path(__file__).resolve().parents[1])
