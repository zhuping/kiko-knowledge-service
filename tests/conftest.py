import os

os.environ["KIKO_KNOWLEDGE_ENVIRONMENT"] = "test"
os.environ["KIKO_KNOWLEDGE_DATABASE_URL"] = "sqlite://"
os.environ["KIKO_KNOWLEDGE_CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["KIKO_KNOWLEDGE_CLASSIFIER_API_KEY"] = ""
os.environ["KIKO_KNOWLEDGE_CLASSIFIER_MODEL"] = ""

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, engine
from app.core.security import AdminContext
from app.domains.gold_regression.service import run as run_regression
from app.main import app
from app.models import Base
from app.schemas.classification import ClassifierDecision


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def admin_headers():
    return {"X-Admin-Subject": "admin", "X-Admin-Roles": "admin"}


@pytest.fixture
def editor_headers():
    return {"X-Admin-Subject": "editor", "X-Admin-Roles": "editor,viewer"}


@pytest.fixture
def reviewer_headers():
    return {"X-Admin-Subject": "reviewer", "X-Admin-Roles": "reviewer,viewer"}


@pytest.fixture
def publisher_headers():
    return {"X-Admin-Subject": "publisher", "X-Admin-Roles": "publisher,viewer"}


@pytest.fixture
def seeded(
    client,
    admin_headers,
    editor_headers,
    reviewer_headers,
    publisher_headers,
):
    response = client.post(
        "/api/v1/admin/packages",
        headers=editor_headers,
        json={
            "code": "PEP-MATH-G1-U",
            "subject_code": "math",
            "grade": 1,
            "semester": "upper",
            "edition": "PEP 2024",
            "publisher": "人民教育出版社",
            "initial_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    package = response.json()["data"]["package"]
    version = response.json()["data"]["version"]
    base = f"/api/v1/admin/packages/{package['id']}/versions/{version['id']}"
    nodes = []
    for order, (code, name) in enumerate(
        [("U1", "准备课"), ("U2", "5以内加减法")], start=1
    ):
        response = client.post(
            f"{base}/catalog",
            headers=editor_headers,
            json={
                "node_type": "unit",
                "code": code,
                "name": name,
                "order_no": order,
                "source": {"book": "一年级数学", "page": order},
            },
        )
        assert response.status_code == 201, response.text
        nodes.append(response.json()["data"])
    objectives = []
    objective_payloads = [
        (
            nodes[0]["id"],
            "ADD-5",
            "5以内加法",
            "计算 5 以内两个数的和",
            ["加法"],
            ["相加"],
            "1 + 1 = ?",
        ),
        (
            nodes[1]["id"],
            "SUB-5",
            "5以内减法",
            "计算 5 以内两个数的差",
            ["减法"],
            ["相减"],
            "3 - 1 = ?",
        ),
    ]
    for (
        node_id,
        code,
        name,
        definition,
        concepts,
        actions,
        question,
    ) in objective_payloads:
        response = client.post(
            f"{base}/objectives",
            headers=editor_headers,
            json={
                "node_id": node_id,
                "code": code,
                "name": name,
                "definition": definition,
                "attainment": f"能正确{name}",
                "required_concepts": concepts,
                "required_actions": actions,
                "allowed_variations": ["数字和语境可以变化"],
                "exclusions": ["不含多步运算"],
                "match_hints": [name],
                "source": {"book": "一年级数学", "page": 10},
            },
        )
        assert response.status_code == 201, response.text
        objective = response.json()["data"]
        objectives.append(objective)
        response = client.post(
            f"{base}/exemplars",
            headers=editor_headers,
            json={
                "exemplar_type": "prototype",
                "source_type": "textbook",
                "source": {
                    "title": "一年级数学",
                    "page": 10,
                    "question_no": code,
                },
                "question_text": question,
                "answer": "2",
                "solution_text": f"使用{actions[0]}计算",
                "task_signature": {
                    "question_goal": name,
                    "required_method": actions,
                    "required_concepts": concepts,
                    "input_form": ["文本"],
                    "output_form": ["数值"],
                    "difficulty_features": [],
                },
                "display_level": "reference",
                "objectives": [{"objective_id": objective["id"], "role": "primary"}],
            },
        )
        assert response.status_code == 201, response.text
    response = client.post(
        f"{base}/relations",
        headers=editor_headers,
        json={
            "source_objective_id": objectives[0]["id"],
            "target_objective_id": objectives[1]["id"],
            "relation_type": "prerequisite_of",
        },
    )
    assert response.status_code == 201, response.text
    response = client.post(
        f"{base}/mappings",
        headers=editor_headers,
        json={
            "objective_id": objectives[0]["id"],
            "namespace": "kiko-current-product",
            "external_id": "legacy-add-5",
        },
    )
    assert response.status_code == 201, response.text
    assert (
        client.post(f"{base}/submit-review", headers=editor_headers).status_code == 200
    )
    assert (
        client.post(
            f"{base}/approve",
            headers=reviewer_headers,
            json={"note": "审核通过"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/admin/gold-tests",
            headers=reviewer_headers,
            json={
                "package_id": package["id"],
                "question": {
                    "text": "1 + 1 = ?",
                    "options": [],
                    "media_urls": [],
                },
                "scope_context": {"active_node_ids": [nodes[0]["logical_id"]]},
                "expected": {
                    "primary_objective_id": objectives[0]["logical_id"],
                    "match_type": "direct",
                    "scope_status": "in_scope",
                },
            },
        ).status_code
        == 201
    )

    def choose(_question, candidates):
        candidate = candidates[0]
        return ClassifierDecision(
            primary_objective_id=candidate["objective_id"],
            match_type="direct",
            evidence_exemplar_ids=[
                item["exemplar_id"] for item in candidate["exemplars"][:1]
            ],
            reason_summary="发布回归通过",
        )

    with SessionLocal() as db:
        regression = run_regression(
            db,
            AdminContext("reviewer", frozenset({("reviewer", None)})),
            version["id"],
            classify_fn=choose,
        )
        assert regression.passed
    assert client.post(f"{base}/publish", headers=publisher_headers).status_code == 200
    response = client.post(
        "/api/v1/admin/client-apps",
        headers=admin_headers,
        json={
            "code": "current-product",
            "name": "当前产品",
            "allowed_package_ids": [package["id"]],
            "allowed_media_hosts": ["media.example.com"],
            "rate_limit_per_minute": 60,
        },
    )
    assert response.status_code == 201, response.text
    client_app = response.json()["data"]
    return {
        "package": package,
        "version": version,
        "nodes": nodes,
        "objectives": objectives,
        "client_app": client_app,
        "auth": {"Authorization": f"Bearer {client_app['api_key']}"},
    }
