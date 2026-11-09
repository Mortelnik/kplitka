"""Real runtime execution, without commercial attestations or patched business rules."""

import csv
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from docx import Document

from kp_plugin import production
from kp_plugin.engine.calculation import calculate_offer
from kp_plugin.llm.p4_catalog import CATALOG_FIELDS, STOCK_FIELDS, load_p4_catalog

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/fish-kp/skills/generate-fish-kp/scripts/run_production.py"


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def payload(tmp_path):
    folder = tmp_path / "profile"
    folder.mkdir()
    # Explicit TEST ONLY inputs; no commercial attestation is issued for them.
    catalog = dict.fromkeys(sorted(CATALOG_FIELDS), "")
    catalog.update(product_id="P1", name="Учебный товар", unit="т", status="active",
                   source_ref="TEST ONLY catalog", is_fictional="да", container_capacity_tons="26")
    write_csv(folder / "catalog.csv", [catalog])
    stock = dict.fromkeys(sorted(STOCK_FIELDS), "")
    stock.update(line_id="S1", product_id="P1", batch="TEST", stock_tons="50",
                 status="active", source_ref="TEST ONLY stock", is_fictional="да", actual_date="2026-11-09")
    write_csv(folder / "warehouse_stock.csv", [stock])
    write_csv(folder / "price.csv", [{"product_id": "P1", "unit_price_rub_per_t": "100",
                                     "tax_rate": "0.1", "currency": "RUB", "source_ref": "TEST ONLY price"}])
    (folder / "rules.json").write_text(json.dumps({"pricing": {"currency": "RUB"},
                                                  "discounts": {"rules": []}}), encoding="utf-8")
    profile = load_p4_catalog(folder / "catalog.csv", folder / "warehouse_stock.csv",
                              as_of=production.date(2026, 11, 9))
    return {"profile_dir": str(folder), "raw_text": "Учебный товар 2.5 т",
            "needs": {"items": [{"product_name": "Учебный товар", "quantity": "2.5", "unit": "т"}]},
            "as_of": "2026-11-09", "settings": {"input_sources": [
                {**profile.products[0].sources[0].model_dump(), "confirmed": True}]}}


def run(payload, tmp_path):
    return production.run_production(production.ProductionInput.model_validate_json(json.dumps(payload)),
                                     tmp_path / "output", base_dir=tmp_path)


def test_real_p2_executes_but_commercial_gate_stays_closed(payload, tmp_path, monkeypatch):
    assert production.calculate_offer is calculate_offer
    actual = production.run_flow
    calls = []

    def observed(*args, **kwargs):
        assert kwargs["calculate_offer"] is calculate_offer
        flow = actual(*args, **kwargs)
        calls.append(flow)
        return flow

    monkeypatch.setattr(production, "run_flow", observed)
    before = deepcopy(payload)
    result = run(payload, tmp_path)
    assert len(calls) == 1 and calls[0].calculation.successful_calculation
    assert result["calculation"]["total"] == production.Decimal("275.00")
    assert result["gate_status"] == "INTERNAL_DRAFT"
    assert result["client_offer"] is False
    assert result["trusted_inputs"] is False and result["complete_delivery_cost"] is False
    assert result["blockers"] and not result["profile_errors"]
    assert "INTERNAL_DRAFT" in "\n".join(p.text for p in Document(result["document_path"]).paragraphs)
    assert payload == before
    saved = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert saved["calculation"]["total"] == "275.00"
    assert saved["p2_implementation"].startswith("sha256:")


@pytest.mark.parametrize("change", ["source", "quantity", "rules"])
def test_unconfirmed_or_invalid_inputs_refuse_p2(payload, tmp_path, monkeypatch, change):
    if change == "source":
        payload["settings"] = {}
    elif change == "quantity":
        payload["raw_text"] = "Учебный товар"
    else:
        folder = Path(payload["profile_dir"])
        (folder / "rules.json").write_text(json.dumps({"pricing": {"currency": "RUB"}, "discounts": {
            "rules": [{"id": "unknown", "type": "loyalty"}]}}), encoding="utf-8")

    def forbidden(**kwargs):
        pytest.fail("P2 must not execute with invalid or unconfirmed inputs")

    monkeypatch.setattr(production, "calculate_offer", forbidden)
    result = run(payload, tmp_path)
    assert result["calculation"] is None
    assert not result["successful_calculation"] and not result["client_offer"]
    assert result["gate_status"] == "INTERNAL_DRAFT"
    assert result["calculation_diagnostics"]
    if change == "rules":
        assert result["profile_errors"]


def invoke(source, output, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), "--runtime-root", str(ROOT),
                           "--input", str(source), "--output-dir", str(output)], cwd=cwd,
                          env={**os.environ, "PYTHONUTF8": "1"},
                          capture_output=True, text=True, encoding="utf-8", check=False)


def test_skill_script_real_run_json_and_preserved_outputs(payload, tmp_path):
    payload["profile_dir"] = "profile"
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    first = invoke(source, tmp_path / "output", ROOT)
    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)
    assert payload["ok"] is True and payload["client_offer"] is False
    assert payload["calculation"]["total"] == "275.00"
    assert payload == json.loads(Path(payload["summary_path"]).read_text(encoding="utf-8"))
    assert Path(payload["document_path"]).is_absolute()
    before = Path(payload["document_path"]).read_bytes()
    second = invoke(source, tmp_path / "output", tmp_path)
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["document_path"] != payload["document_path"]
    assert Path(payload["document_path"]).read_bytes() == before


def test_fish_demo_validation_and_data_preserved(tmp_path):
    folder = ROOT / "profiles/examples/fish_demo"
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    completed = invoke(ROOT / "docs/tasks/p3-production-wiring/fish-demo-input.json", tmp_path, tmp_path)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["profile_errors"] and result["blockers"]
    assert result["calculation"] is None and result["successful_calculation"] is False
    assert result["document_kind"] == "internal_diagnostic"
    assert result["gate_status"] == "INTERNAL_DRAFT" and result["client_offer"] is False
    assert Path(result["document_path"]).is_file() and Path(result["summary_path"]).is_file()
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


@pytest.mark.parametrize("text", ["{invalid", '{"unknown": true}'])
def test_skill_invalid_json_is_structured_failure(tmp_path, text):
    source = tmp_path / "bad.json"
    source.write_text(text, encoding="utf-8")
    result = invoke(source, tmp_path / "output", tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stdout)["ok"] is False
    assert not (tmp_path / "output").exists()
