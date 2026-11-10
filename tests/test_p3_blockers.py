"""Regressions for handoff B1/B2; all attestations are explicitly TEST ONLY."""

from copy import deepcopy
from dataclasses import replace
from datetime import date

import pytest
import test_p2_published as published
from test_docgen import test_real_p2_reference_if_available as legacy_reference
from test_docgen_gate import setup_gate
from test_orchestrator import _test_attestor

from kp_plugin.docgen.gate import (
    ConstraintReview,
    ConstraintStatus,
    GateStatus,
    constraint_review_fingerprint,
    evaluate_gate,
    generate_commercial_document,
    generate_internal_draft,
)
from kp_plugin.llm.needs import EvidenceRef
from kp_plugin.llm.p2_adapter import prepare_p2_invocation, run_p2
from kp_plugin.llm.selection import select_products
from kp_plugin.llm.selection_bridge import assess_selection

TODAY = date(2026, 10, 28)


def unknown_constraints_case():
    data, *_ = setup_gate()
    data['needs'].unknown_fields = ['constraints']
    data['needs'].model_payload['constraints'] = ['TEST ONLY unresolved condition']
    data['selection'] = select_products(data['needs'], data['profile'].products)
    result = run_p2(**data, calculate_offer=published.core.__wrapped__())
    current = prepare_p2_invocation(**data)
    assessment = assess_selection(data['needs'], data['selection'], data['profile'],
                                  calculation=result.evidence, calculation_context=current.bridge_context,
                                  confirmed_sources=data['settings'].input_sources)
    return data, result, current, assessment


def test_unknown_top_level_constraints_block_commercial_approval():
    _, result, current, assessment = unknown_constraints_case()
    decision = evaluate_gate(result, current, assessment, attestation=_test_attestor(result), as_of=TODAY)
    assert decision.status == GateStatus.INTERNAL_DRAFT


def test_legacy_reference_with_actual_published_p2(monkeypatch):
    import kp_plugin.engine.calculation as local
    monkeypatch.setattr(local, 'calculate_offer', published.core.__wrapped__(), raising=False)
    legacy_reference()


def constraint_case(scope='request', constraint='TEST ONLY customer condition'):
    data, *_ = setup_gate()
    subject = data['needs'] if scope == 'request' else data['needs'].items[0]
    subject.constraints = [constraint]
    subject.evidence[f'constraint:{constraint}'] = EvidenceRef(field_name='constraints', quote=constraint, verified=True)
    data['selection'] = select_products(data['needs'], data['profile'].products)
    result = run_p2(**data, calculate_offer=published.core.__wrapped__())
    current = prepare_p2_invocation(**data)
    assessment = assess_selection(data['needs'], data['selection'], data['profile'],
                                  calculation=result.evidence, calculation_context=current.bridge_context,
                                  confirmed_sources=data['settings'].input_sources)
    review = ConstraintReview(status=ConstraintStatus.CONFIRMED,
                              context_fingerprint=constraint_review_fingerprint(result, current),
                              sources=data['settings'].input_sources,
                              product_compatible=True, calculation_compatible=True, terms_compatible=True)
    attestation = replace(_test_attestor(result), constraints=review)
    return data, result, current, assessment, attestation


@pytest.mark.parametrize('scope', ['request', 'item'])
def test_explicit_verified_compatible_constraints_pass_without_mutation(scope):
    data, result, current, assessment, attestation = constraint_case(scope)
    before = deepcopy((data, assessment))
    decision = evaluate_gate(result, current, assessment, attestation=attestation, as_of=TODAY)
    assert decision.status == GateStatus.COMMERCIALLY_APPROVED, decision.blockers
    assert assessment.problems  # Raw bridge diagnostic retained, resolved only by external review at gate.
    assert (data, assessment) == before
    assert decision.assessment.needs.evidence == assessment.needs.evidence


@pytest.mark.parametrize('change,expected', [
    ('missing', 'constraints_review_missing_or_unknown'),
    ('unknown', 'constraints_review_missing_or_unknown'),
    ('contradictory', 'constraints_contradictory'),
    ('sources', 'constraints_sources_unconfirmed'),
    ('product', 'constraints_incompatible:product_compatible'),
    ('calculation', 'constraints_incompatible:calculation_compatible'),
    ('terms', 'constraints_incompatible:terms_compatible'),
    ('absence', 'constraints_presence_conflict'),
    ('stale', 'constraints_review_stale'),
    ('unverified', 'constraints_unconfirmed:request'),
])
def test_unknown_conflicting_or_incompatible_review_blocks(change, expected, tmp_path):
    _, result, current, assessment, attestation = constraint_case()
    review = attestation.constraints
    if change == 'missing':
        review = None
    elif change in {'unknown', 'contradictory'}:
        review = replace(review, status=ConstraintStatus(change))
    elif change == 'sources':
        review = replace(review, sources=())
    elif change in {'product', 'calculation', 'terms'}:
        review = replace(review, **{f'{change}_compatible': False})
    elif change == 'absence':
        review = replace(review, absence_confirmed=True)
    elif change == 'stale':
        review = replace(review, context_fingerprint='outdated')
    else:
        key = next(iter(assessment.needs.evidence))
        assessment.needs.evidence[key] = EvidenceRef(field_name='constraints', quote='TEST ONLY', verified=False)
    attestation = replace(attestation, constraints=review)
    decision = evaluate_gate(result, current, assessment, attestation=attestation, as_of=TODAY)
    assert decision.status == GateStatus.INTERNAL_DRAFT
    assert expected in decision.blockers
    path = generate_internal_draft(decision, tmp_path/'draft.docx')
    from docx import Document
    assert expected in '\n'.join(p.text for p in Document(path).paragraphs)
    with pytest.raises(ValueError, match='Commercial generation blocked'):
        generate_commercial_document(result, current, assessment, tmp_path/'blocked.docx',
                                     attestation=attestation, as_of=TODAY)
    assert not (tmp_path/'blocked.docx').exists()


@pytest.mark.parametrize('scope', ['request', 'item'])
def test_empty_unknown_constraints_never_become_confirmed_absence(scope):
    _data, result, current, assessment = unknown_constraints_case()
    if scope == 'item':
        assessment.needs.unknown_fields = []
        assessment.needs.items[0].unknown_fields = ['constraints']
    before = deepcopy(assessment.needs)
    decision = evaluate_gate(result, current, assessment, attestation=_test_attestor(result), as_of=TODAY)
    assert decision.status == GateStatus.INTERNAL_DRAFT
    assert any(b.startswith('constraints_unknown:') for b in decision.blockers)
    assert decision.assessment.needs.unknown_fields == before.unknown_fields
    assert decision.assessment.needs.model_payload == before.model_payload


def test_absence_requires_explicit_confirmed_review():
    _, result, current, assessment, attestation = setup_gate()
    attestation = replace(attestation, constraints=replace(attestation.constraints, absence_confirmed=False))
    decision = evaluate_gate(result, current, assessment, attestation=attestation, as_of=TODAY)
    assert 'constraints_absence_unconfirmed' in decision.blockers


def test_changed_constraint_invalidates_old_review_even_with_new_price_attestation():
    _, _, _, _, old = constraint_case(constraint='TEST ONLY A')
    _, result, current, assessment, new = constraint_case(constraint='TEST ONLY B')
    decision = evaluate_gate(result, current, assessment,
                             attestation=replace(new, constraints=old.constraints), as_of=TODAY)
    assert 'constraints_review_stale' in decision.blockers


def test_constraint_review_does_not_override_unknown_stock():
    _, result, current, assessment, attestation = constraint_case()
    product = assessment.profile.products[0].model_copy(update={'stock_quantity': None, 'stock_sources': ()})
    profile = replace(assessment.profile, products=(product,))
    assessment = replace(assessment, profile=profile, selection=select_products(assessment.needs, profile.products))
    decision = evaluate_gate(result, current, assessment, attestation=attestation, as_of=TODAY)
    assert decision.status == GateStatus.INTERNAL_DRAFT
    assert 'blocking_problems' in decision.blockers
