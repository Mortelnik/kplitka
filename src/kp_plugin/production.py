"""Local JSON entry point: existing profile loaders -> run_flow -> real P2.

Structured input is supplied after clarification, not extracted by a real LLM.
No commercial attestation or input trust is manufactured by this boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from kp_plugin.engine.calculation import calculate_offer
from kp_plugin.llm.needs import NeedsExtractor
from kp_plugin.llm.p2_adapter import P2Settings
from kp_plugin.llm.p4_catalog import load_p4_catalog
from kp_plugin.orchestrator import Answer, run_flow
from kp_plugin.profile.loader import load_catalog, load_prices, load_rules
from kp_plugin.profile.validator import validate_profile


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field_name: str
    position: int | None = None
    value: object


class ProductionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    profile_dir: Path
    raw_text: str = Field(min_length=1)
    needs: dict
    as_of: date
    max_stock_age_days: int | None = Field(default=None, ge=0)
    settings: P2Settings = Field(default_factory=P2Settings)
    answers: tuple[AnswerInput, ...] = ()


@dataclass
class StructuredNeedsClient:
    """Manual structured input, still checked against raw_text by NeedsExtractor."""

    payload: dict

    def extract_needs(self, raw_text: str) -> dict:
        return deepcopy(self.payload)


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value):
    if isinstance(value, (Decimal, Path, date)):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def run_production(request: ProductionInput, output_dir: Path, *, base_dir: Path) -> dict:
    """Run the full flow, retaining profile validation failures as diagnostics.

    Paths in the request resolve against its JSON file, never the process cwd.
    Source confirmations must be explicitly supplied by an authorized caller;
    hashes identify artifacts and do not authenticate their business contents.
    """
    folder = (base_dir / request.profile_dir).resolve()
    catalog_path, price_path = folder / "catalog.csv", folder / "price.csv"
    rules_path = folder / "rules.json"
    catalog = load_catalog(catalog_path)
    prices = load_prices(price_path)
    rules = load_rules(rules_path)
    errors = validate_profile(catalog, prices, rules)
    profile = load_p4_catalog(catalog_path, folder / "warehouse_stock.csv", as_of=request.as_of,
                              max_stock_age_days=request.max_stock_age_days)
    # Bind the actual executed source artifact, not a caller-supplied label.
    from kp_plugin.engine import calculation

    settings = request.settings.model_copy(update={
        "profile_id": request.settings.profile_id or folder.name,
        "profile_version": _hash(catalog_path),
        "price_snapshot_id": _hash(price_path),
        "p2_implementation": _hash(Path(calculation.__file__)),
        "currency": request.settings.currency or rules.get("pricing", {}).get("currency"),
        # Failed mandatory validation must not reach P2, even with source claims.
        "input_sources": () if errors else request.settings.input_sources,
    })
    output_dir = output_dir.resolve()
    flow = run_flow(
        request.raw_text, extractor=NeedsExtractor(StructuredNeedsClient(request.needs)),
        profile=profile, settings=settings, catalog=catalog, prices=prices, rules=rules,
        calculate_offer=calculate_offer, output_path=output_dir / "offer.docx",
        answers=tuple(Answer(a.field_name, a.position, a.value) for a in request.answers),
        confirmed_sources=settings.input_sources, as_of=request.as_of,
    )
    summary_path = flow.document.with_suffix(".json")
    summary = {
        "ok": True,
        "document_path": str(flow.document.resolve()),
        "summary_path": str(summary_path.resolve()),
        "document_kind": "internal_diagnostic",
        "client_offer": False,
        "gate_status": flow.decision.status.value,
        "blockers": list(flow.decision.blockers),
        "warnings": list(flow.decision.warnings),
        "profile_errors": errors,
        "selection_statuses": [p.status.value for p in flow.selection.positions],
        "successful_calculation": flow.calculation.successful_calculation,
        "trusted_inputs": flow.calculation.trusted_inputs,
        "complete_delivery_cost": flow.calculation.complete_delivery_cost,
        "calculation": flow.calculation.raw_output,
        "calculation_diagnostics": list(flow.calculation.diagnostics),
        "remaining_questions": [asdict(q) for q in flow.remaining_questions],
        "p2_implementation": settings.p2_implementation,
        "extraction_mode": "manual_structured_input",
    }
    # The entry point supplies no attestation: the unchanged gate stays closed.
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, default=_json_default, allow_nan=False)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = ProductionInput.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
        result = run_production(request, args.output_dir, base_dir=args.input.resolve().parent)
    except (OSError, ValueError, TypeError, ArithmeticError) as error:
        result = {"ok": False, "error_type": type(error).__name__, "error": str(error)}
        code = 2
    else:
        code = 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, default=_json_default, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
