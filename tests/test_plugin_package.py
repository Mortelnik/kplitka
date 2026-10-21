import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/fish-kp"
SKILL = PLUGIN / "skills/generate-fish-kp"
SCRIPT = SKILL / "scripts/smoke_docx.py"


def load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_docx", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_and_marketplace_paths():
    manifest = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "fish-kp"
    assert manifest["$schema"].endswith("/1.0.0/plugin.schema.json")
    assert marketplace["plugins"][0]["name"] == manifest["name"]
    assert (ROOT / marketplace["plugins"][0]["source"]["path"]).resolve() == PLUGIN.resolve()
    assert (SKILL / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: generate-fish-kp\n")
    for path in [
        "scripts/requirements-smoke.txt", "scripts/smoke_docx.py",
        "assets/smoke-input.json", "assets/template_kp.docx",
        "references/runtime-check.md", "references/workflow.md",
    ]:
        assert (SKILL / path).is_file()


def test_standalone_copy_generates_readable_document(tmp_path):
    # A cached installation must not depend on src/ or repository-relative paths.
    installed = tmp_path / "installed-plugin"
    shutil.copytree(PLUGIN, installed)
    skill = installed / "skills/generate-fish-kp"
    command = [
        sys.executable, str(skill / "scripts/smoke_docx.py"),
        "--input", str(skill / "assets/smoke-input.json"),
        "--output-dir", str(tmp_path / "output"),
    ]
    run = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=True)
    payload = json.loads(run.stdout)
    assert payload["calculation"]["subtotal"] == "2000000.00"
    assert payload["calculation"]["tax"] == "200000.00"
    assert payload["calculation"]["total"] == "2200000.00"
    assert payload["client_delivery_verified"] is False
    target = Path(payload["document_path"])
    assert target.is_file()
    assert len(payload["sha256"]) == 64
    doc = Document(target)
    assert doc.tables[0].rows[-1].cells[1].text == "2200000.00"
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(second.stdout)["document_path"] != payload["document_path"]


@pytest.mark.parametrize("key,value", [
    ("quantity_tons", "0"), ("quantity_tons", "NaN"),
    ("unit_price", 100000.0), ("unit_price", "-1"),
    ("tax_rate", "1.01"), ("currency", "руб."),
    ("mode", "real-offer"), ("unknown", "value"),
])
def test_invalid_inputs_are_rejected(key, value):
    data = json.loads((SKILL / "assets/smoke-input.json").read_text(encoding="utf-8"))
    data[key] = value
    with pytest.raises(ValueError):
        load_smoke().calculate(data)


def test_bad_json_returns_structured_error(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text("{invalid", encoding="utf-8")
    run = subprocess.run([
        sys.executable, str(SCRIPT), "--input", str(source),
        "--output-dir", str(tmp_path / "output"),
    ], check=False, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 2
    assert json.loads(run.stdout)["ok"] is False
    assert not (tmp_path / "output").exists()
