import csv
import io
import json

from app.providers import classifier
from app.schemas.classification import ClassifierDecision


def _document():
    return {
        "nodes": [
            {
                "logical_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "node_type": "unit",
                "code": "U1",
                "name": "第一单元",
                "order_no": 1,
                "source": {"page": 1},
            }
        ],
        "objectives": [
            {
                "logical_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                "node_logical_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                "code": "COUNT",
                "name": "数数",
                "definition": "按顺序数出物体数量",
                "attainment": "能正确数数",
                "required_concepts": ["数量"],
                "required_actions": ["数数"],
                "allowed_variations": ["物体变化"],
                "exclusions": ["不含加减法"],
                "source": {"page": 1},
            }
        ],
        "relations": [],
        "exemplars": [
            {
                "logical_id": "01ARZ3NDEKTSV4RRFFQ69G5FAX",
                "exemplar_type": "prototype",
                "source_type": "textbook",
                "source": {"title": "测试教材", "page": 1},
                "question_text": "图中有几个圆？",
                "solution_text": "逐个数数",
                "task_signature": {"question_goal": "数数"},
                "display_level": "reference",
                "objectives": [
                    {
                        "objective_logical_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                        "role": "primary",
                    }
                ],
            }
        ],
        "mappings": [
            {
                "objective_logical_id": "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                "namespace": "legacy",
                "external_id": "count",
            }
        ],
    }


def _empty_package(client, editor_headers, code):
    return client.post(
        "/api/v1/admin/packages",
        headers=editor_headers,
        json={
            "code": code,
            "subject_code": "math",
            "grade": 1,
            "semester": "upper",
            "edition": "导入测试",
        },
    ).json()["data"]


def test_json_import_is_previewed_atomic_and_idempotent(client, editor_headers):
    created = _empty_package(client, editor_headers, "IMPORT-JSON")
    package_id = created["package"]["id"]
    version_id = created["version"]["id"]
    base = f"/api/v1/admin/packages/{package_id}/versions/{version_id}"
    request = {"format": "json", "content": json.dumps(_document())}
    preview = client.post(f"{base}/imports", headers=editor_headers, json=request)
    assert preview.status_code == 201
    job = preview.json()["data"]
    assert job["status"] == "validated"
    assert job["preview_json"]["objectives"] == 1
    duplicate = client.post(f"{base}/imports", headers=editor_headers, json=request)
    assert duplicate.json()["data"]["id"] == job["id"]
    confirmed = client.post(
        f"/api/v1/admin/import-jobs/{job['id']}/confirm",
        headers=editor_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "imported"
    objectives = client.get(f"{base}/objectives", headers=editor_headers).json()["data"]
    assert objectives[0]["logical_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAW"


def test_csv_import_and_invalid_document(client, editor_headers):
    created = _empty_package(client, editor_headers, "IMPORT-CSV")
    package_id = created["package"]["id"]
    version_id = created["version"]["id"]
    base = f"/api/v1/admin/packages/{package_id}/versions/{version_id}"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["record_type", "payload_json"])
    writer.writeheader()
    for section, rows in _document().items():
        for row in rows:
            writer.writerow(
                {
                    "record_type": section,
                    "payload_json": json.dumps(row, ensure_ascii=False),
                }
            )
    preview = client.post(
        f"{base}/imports",
        headers=editor_headers,
        json={"format": "csv", "content": buffer.getvalue()},
    )
    assert preview.status_code == 201
    assert preview.json()["data"]["status"] == "validated"

    invalid = _document()
    invalid["objectives"][0]["node_logical_id"] = "missing"
    failed = client.post(
        f"{base}/imports",
        headers=editor_headers,
        json={"format": "json", "content": json.dumps(invalid)},
    )
    assert failed.status_code == 201
    assert failed.json()["data"]["status"] == "failed"
    confirm = client.post(
        f"/api/v1/admin/import-jobs/{failed.json()['data']['id']}/confirm",
        headers=editor_headers,
    )
    assert confirm.status_code == 422


def test_gold_regression_updates_metrics(client, seeded, reviewer_headers, monkeypatch):
    def choose(_question, candidates):
        candidate = candidates[0]
        return ClassifierDecision(
            primary_objective_id=candidate["objective_id"],
            match_type="direct",
            evidence_exemplar_ids=[
                item["exemplar_id"] for item in candidate["exemplars"][:1]
            ],
            reason_summary="黄金用例匹配",
        )

    monkeypatch.setattr(classifier, "classify", choose)
    created = client.post(
        "/api/v1/admin/gold-tests",
        headers=reviewer_headers,
        json={
            "package_id": seeded["package"]["id"],
            "question": {
                "text": "1 + 1 = ?",
                "options": [],
                "media_urls": [],
            },
            "scope_context": {"active_node_ids": [seeded["nodes"][0]["logical_id"]]},
            "expected": {
                "primary_objective_id": seeded["objectives"][0]["logical_id"],
                "match_type": "direct",
                "scope_status": "in_scope",
            },
        },
    )
    assert created.status_code == 201
    run = client.post(
        f"/api/v1/admin/regression-runs/{seeded['version']['id']}",
        headers=reviewer_headers,
    )
    assert run.status_code == 201, run.text
    assert run.json()["data"]["passed"] is True
    assert run.json()["data"]["metrics_json"]["top5_recall"] == 1
    assert client.get("/api/v1/admin/regression-runs", headers=reviewer_headers).json()[
        "data"
    ]
    assert client.get("/api/v1/admin/gold-tests", headers=reviewer_headers).json()[
        "data"
    ]
    assert client.get("/api/v1/admin/audit-logs", headers=reviewer_headers).json()[
        "data"
    ]
