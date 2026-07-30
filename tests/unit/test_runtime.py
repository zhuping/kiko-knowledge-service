import pytest

from app.core.database import SessionLocal
from app.domains.classification.runtime import (
    _tokens,
    confidence,
    normalize_question,
    retrieve,
    validate_decision,
)
from app.schemas.classification import ClassifierDecision


def test_normalization_preserves_math_and_is_stable():
    request = {
        "question": {
            "text": "  １＋１　＝？ ",
            "options": ["Ａ．１", "Ｂ．２"],
            "answer": {"value": 2},
            "structured_content": {"operator": "addition"},
        }
    }
    normalized = normalize_question(request)
    assert "1+1 =?" in normalized
    assert "A.1" in normalized
    assert '{"value": 2}' in normalized
    assert _tokens(normalized) == _tokens(normalized)


def test_retrieval_and_decision_whitelist(seeded):
    with SessionLocal() as db:
        candidates, exemplars, links = retrieve(
            db, [seeded["version"]["id"]], "1 + 1 = ?"
        )
        assert candidates
        assert candidates[0].objective.code == "ADD-5"
        exemplar_id = candidates[0].exemplar_ids[0]
        decision = ClassifierDecision(
            primary_objective_id=candidates[0].objective.id,
            match_type="direct",
            evidence_exemplar_ids=[exemplar_id],
            reason_summary="匹配",
        )
        validate_decision(decision, candidates, exemplars, links)
        assert confidence(decision, candidates) >= 0.65

        invalid = ClassifierDecision(
            primary_objective_id="not-a-candidate",
            match_type="direct",
            reason_summary="越界",
        )
        with pytest.raises(ValueError):
            validate_decision(invalid, candidates, exemplars, links)

        invalid_evidence = ClassifierDecision(
            primary_objective_id=candidates[0].objective.id,
            match_type="direct",
            evidence_exemplar_ids=["missing"],
            reason_summary="证据越界",
        )
        with pytest.raises(ValueError):
            validate_decision(invalid_evidence, candidates, exemplars, links)


def test_classifier_decision_rejects_invalid_unmatched():
    with pytest.raises(ValueError):
        ClassifierDecision(
            primary_objective_id="objective",
            match_type="unmatched",
            reason_summary="不合法",
        )
