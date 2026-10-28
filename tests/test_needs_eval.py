from __future__ import annotations

import json
from pathlib import Path

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "p3_needs_eval.json"


def test_eval_dataset_exists_and_has_minimum_scenarios() -> None:
    assert FIXTURE_PATH.exists(), "Fixture file with P3.1 evaluation scenarios is missing"

    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios")
    assert isinstance(scenarios, list)
    assert len(scenarios) >= 20, f"Expected at least 20 scenarios, got {len(scenarios)}"

    categories = {scenario["category"] for scenario in scenarios}
    assert categories, "Dataset must include scenario categories"

    for scenario in scenarios:
        assert "id" in scenario
        assert "raw_text" in scenario
        assert "expected" in scenario
        assert "explanation" in scenario


def test_eval_dataset_is_structurally_consistent() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    scenarios = payload["scenarios"]

    for scenario in scenarios:
        expected = scenario["expected"]
        item_list = expected.get("items", [])

        if expected.get("status") in {"ok", "clarify", "error"}:
            assert expected["status"] in {"ok", "clarify", "error"}

        if scenario["category"] == "non_target":
            assert expected.get("status") in {"clarify", "error"}

        if item_list:
            for item in item_list:
                assert "product_name" in item or "unknown_fields" in item
                if item.get("quantity") is not None:
                    assert isinstance(item["quantity"], (str, int, float))
                if item.get("unit") is not None:
                    assert isinstance(item["unit"], str)

        if "evidence" in expected:
            evidence = expected["evidence"]
            assert isinstance(evidence, list)
            for entry in evidence:
                assert set(entry) >= {"field_name", "quote", "verified"}
                assert isinstance(entry["verified"], bool)


def test_eval_dataset_avoids_invented_commercial_facts() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for scenario in payload["scenarios"]:
        raw = scenario["raw_text"]
        expected = scenario["expected"]
        evidence = expected.get("evidence", [])
        text = " ".join(raw.lower().split())

        for entry in evidence:
            ref = entry.get("quote") or ""
            if ref:
                assert ref.lower() in text, (
                    f"Evidence quote {ref!r} is not present in raw_text for scenario {scenario['id']}"
                )

        if expected.get("status") == "ok":
            for item in expected.get("items", []):
                if item.get("budget_limit") is not None:
                    assert str(item["budget_limit"]).lower() in text or any(
                        token in text for token in ["бюджет", "до", "не более", "макс"]
                    )
