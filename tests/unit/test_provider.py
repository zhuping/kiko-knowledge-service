import pytest
import requests

from app.core.config import settings
from app.providers import classifier


class Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


def test_classifier_parses_constrained_json(monkeypatch):
    monkeypatch.setattr(settings, "classifier_api_key", "secret")
    monkeypatch.setattr(settings, "classifier_model", "model")
    monkeypatch.setattr(
        requests,
        "post",
        lambda *_args, **_kwargs: Response(
            """```json
            {"primary_objective_id":"obj","secondary_objective_ids":[],
             "match_type":"direct","evidence_exemplar_ids":[],
             "task_signature":{},"reason_summary":"匹配"}
            ```"""
        ),
    )
    result = classifier.classify("题目", [{"objective_id": "obj"}])
    assert result.primary_objective_id == "obj"


def test_classifier_retries_then_fails_without_leaking_response(monkeypatch):
    monkeypatch.setattr(settings, "classifier_api_key", "secret")
    monkeypatch.setattr(settings, "classifier_model", "model")
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(1)
        raise requests.Timeout("secret response")

    monkeypatch.setattr(requests, "post", fail)
    with pytest.raises(classifier.ClassifierUnavailable):
        classifier.classify("题目", [])
    assert len(calls) == 3


def test_classifier_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "classifier_api_key", "")
    monkeypatch.setattr(settings, "classifier_model", "")
    with pytest.raises(classifier.ClassifierUnavailable):
        classifier.classify("题目", [])
