from app.providers import classifier
from app.schemas.classification import ClassifierDecision


def fake_classifier(_question, candidates):
    selected = candidates[0]
    evidence = [item["exemplar_id"] for item in selected["exemplars"][:1]]
    return ClassifierDecision(
        primary_objective_id=selected["objective_id"],
        secondary_objective_ids=[],
        match_type="direct",
        evidence_exemplar_ids=evidence,
        task_signature={"question_goal": selected["name"]},
        reason_summary="题目目标和必要方法与教材原型一致",
    )


def _request(seeded, request_id="question-1", text="1 + 1 = ?"):
    return {
        "client_request_id": request_id,
        "source_question_id": "source-1",
        "curriculum_context": {
            "active_package_id": seeded["package"]["id"],
            "active_package_version": "latest_stable",
            "active_node_ids": [seeded["nodes"][0]["logical_id"]],
        },
        "question": {
            "text": text,
            "options": [],
            "media_urls": [],
        },
    }


def test_completed_classification_is_idempotent_and_explainable(
    client, seeded, monkeypatch
):
    monkeypatch.setattr(classifier, "classify", fake_classifier)
    response = client.post(
        "/api/v1/classifications",
        headers=seeded["auth"],
        json=_request(seeded),
    )
    assert response.status_code == 202, response.text
    classification_id = response.json()["data"]["classification_id"]
    repeated = client.post(
        "/api/v1/classifications",
        headers=seeded["auth"],
        json=_request(seeded),
    )
    assert repeated.json()["data"]["classification_id"] == classification_id

    result = client.get(
        f"/api/v1/classifications/{classification_id}",
        headers=seeded["auth"],
    )
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["status"] == "completed"
    assert (
        data["result"]["primary_objective"]["id"]
        == seeded["objectives"][0]["logical_id"]
    )
    assert data["result"]["scope_status"] == "in_scope"
    assert data["result"]["match_type"] == "direct"
    assert data["result"]["evidence"][0]["source_title"] == "一年级数学"
    assert data["result"]["external_mappings"]["kiko-current-product"] == (
        "legacy-add-5"
    )
    assert data["versions"]["classifier"] == "classifier-v1"

    feedback = client.post(
        f"/api/v1/classifications/{classification_id}/feedback",
        headers=seeded["auth"],
        json={
            "feedback_request_id": "feedback-1",
            "confirmed": True,
            "reason": "确认正确",
        },
    )
    assert feedback.status_code == 201
    repeat_feedback = client.post(
        f"/api/v1/classifications/{classification_id}/feedback",
        headers=seeded["auth"],
        json={
            "feedback_request_id": "feedback-1",
            "confirmed": True,
            "reason": "确认正确",
        },
    )
    assert (
        repeat_feedback.json()["data"]["feedback_id"]
        == feedback.json()["data"]["feedback_id"]
    )


def test_feedback_review_and_admin_queries(
    client, seeded, monkeypatch, reviewer_headers
):
    monkeypatch.setattr(classifier, "classify", fake_classifier)
    task = client.post(
        "/api/v1/classifications",
        headers=seeded["auth"],
        json=_request(seeded, request_id="question-feedback"),
    ).json()["data"]
    feedback = client.post(
        f"/api/v1/classifications/{task['classification_id']}/feedback",
        headers=seeded["auth"],
        json={
            "confirmed": False,
            "corrected_primary_objective_id": seeded["objectives"][1]["logical_id"],
            "corrected_match_type": "variant",
            "corrected_scope_status": "unknown_scope",
            "reason": "应当是减法目标",
        },
    ).json()["data"]
    reviewed = client.post(
        f"/api/v1/admin/feedback/{feedback['feedback_id']}/review",
        headers=reviewer_headers,
        json={
            "decision": "accepted",
            "action_type": "exemplar_candidate",
            "review_note": "进入下一版样题候选",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["status"] == "accepted"
    detail = client.get(
        f"/api/v1/admin/feedback/{feedback['feedback_id']}",
        headers=reviewer_headers,
    ).json()["data"]
    assert detail["review"]["action_type"] == "exemplar_candidate"
    assert client.get(
        "/api/v1/admin/feedback?status=accepted",
        headers=reviewer_headers,
    ).json()["data"]
    assert client.get(
        "/api/v1/admin/classifications?status=completed",
        headers=reviewer_headers,
    ).json()["data"]
    assert (
        client.get(
            f"/api/v1/admin/classifications/{task['classification_id']}",
            headers=reviewer_headers,
        ).status_code
        == 200
    )


def test_provider_unavailable_keeps_candidates_for_review(client, seeded):
    response = client.post(
        "/api/v1/classifications",
        headers=seeded["auth"],
        json=_request(seeded, request_id="provider-down"),
    )
    task_id = response.json()["data"]["classification_id"]
    data = client.get(
        f"/api/v1/classifications/{task_id}", headers=seeded["auth"]
    ).json()["data"]
    assert data["status"] == "needs_review"
    assert data["failure"]["code"] == "CLASSIFIER_UNAVAILABLE"
    assert data["result"] is None


def test_unmatched_is_not_later_scope(client, seeded, monkeypatch):
    monkeypatch.setattr(classifier, "classify", fake_classifier)
    response = client.post(
        "/api/v1/classifications",
        headers=seeded["auth"],
        json=_request(
            seeded,
            request_id="unmatched",
            text="火星地质年代与玄武岩光谱",
        ),
    )
    task_id = response.json()["data"]["classification_id"]
    data = client.get(
        f"/api/v1/classifications/{task_id}", headers=seeded["auth"]
    ).json()["data"]
    assert data["status"] == "completed"
    assert data["result"]["match_type"] == "unmatched"
    assert data["result"]["scope_status"] == "unknown_scope"
    assert data["result"]["primary_objective"] is None


def test_media_and_scope_inputs_are_validated(client, seeded):
    request = _request(seeded, request_id="bad-media")
    request["question"]["media_urls"] = ["http://127.0.0.1/metadata"]
    response = client.post(
        "/api/v1/classifications", headers=seeded["auth"], json=request
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MEDIA_NOT_ALLOWED"

    request = _request(seeded, request_id="bad-node")
    request["curriculum_context"]["active_node_ids"] = ["unknown-node"]
    response = client.post(
        "/api/v1/classifications", headers=seeded["auth"], json=request
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
