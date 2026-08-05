from __future__ import annotations

import base64
import hashlib
import hmac
import time
from io import BytesIO

from cryptography.fernet import Fernet
from openpyxl import Workbook

from app.models import ApiClient


def admin_post(client, path: str, payload: dict):
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def seed_group(client):
    domain = admin_post(
        client,
        "/api/v1/admin/catalog/nodes",
        {"level": 1, "nodeType": "domain", "title": "数与代数"},
    )["id"]
    topic = admin_post(
        client,
        "/api/v1/admin/catalog/nodes",
        {"level": 2, "nodeType": "topic", "title": "数的认识", "parentId": domain},
    )["id"]
    unit = admin_post(
        client,
        "/api/v1/admin/catalog/nodes",
        {"level": 3, "nodeType": "unit", "title": "100以内", "parentId": topic},
    )["id"]
    group = admin_post(
        client,
        "/api/v1/admin/catalog/nodes",
        {"level": 4, "nodeType": "group", "title": "数数", "parentId": unit},
    )["id"]
    return group


def seed_release(client):
    group = seed_group(client)
    admin_post(
        client,
        "/api/v1/admin/knowledge",
        {
            "canonicalId": "m.num.count.1_100",
            "groupNodeId": group,
            "knowledgeName": "100以内数数",
            "knowledgeType": "skill",
            "gradeTerm": "一年级上册",
            "scope": "core",
            "cognitiveLevel": "remember",
            "importance": "core",
            "coreKeywords": ["数到100"],
            "ocrSignals": ["数到100"],
        },
    )
    admin_post(
        client,
        "/api/v1/admin/textbook-mappings/batch",
        [
            {
                "canonicalId": "m.num.count.1_100",
                "textbookPath": "一上/数的认识",
                "mappingType": "introduction",
            }
        ],
    )
    batch = admin_post(
        client,
        "/api/v1/admin/release-batches",
        {"versionLabel": "2026.08.04.test"},
    )
    assert admin_post(
        client, f"/api/v1/admin/release-batches/{batch['id']}/validate", {}
    )["passed"]
    return admin_post(
        client, f"/api/v1/admin/release-batches/{batch['id']}/publish", {}
    )


def open_headers(
    client,
    app_key: str = "app_test",
    secret: bytes = b"secret",
    allowed_scopes: list[str] | None = None,
):
    with client.app.state.session_factory() as session:
        session.add(
            ApiClient(
                app_key=app_key,
                secret_ciphertext=Fernet(
                    client.app.state.settings.api_secret_key.encode()
                )
                .encrypt(secret)
                .decode(),
                allowed_scopes=allowed_scopes or ["read"],
            )
        )
        session.commit()
    timestamp = str(int(time.time()))
    nonce = f"nonce-{time.time_ns()}"
    empty_hash = hashlib.sha256(b"").hexdigest()
    canonical = "\n".join(
        ["GET", "/api/v1/open/knowledge/tree", empty_hash, empty_hash, timestamp, nonce]
    ).encode()
    signature = base64.b64encode(
        hmac.new(secret, canonical, hashlib.sha256).digest()
    ).decode()
    return {
        "X-App-Key": app_key,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


def test_publish_and_read_immutable_tree(client):
    release = seed_release(client)
    releases = client.get(
        "/api/v1/admin/releases", params={"pageNum": 1, "pageSize": 20}
    ).json()["data"]
    assert releases["total"] == 1
    assert releases["list"][0]["versionLabel"] == release["versionLabel"]
    mappings = client.get(
        "/api/v1/admin/textbook-mappings",
        params={"pageNum": 1, "pageSize": 20},
    ).json()["data"]
    assert mappings["total"] == 1
    assert mappings["list"][0]["canonicalId"] == "m.num.count.1_100"
    response = client.get("/api/v1/open/knowledge/tree", headers=open_headers(client))
    assert response.status_code == 200
    assert response.json()["meta"]["releaseVersion"] == release["versionLabel"]
    leaf = response.json()["data"][0]["children"][0]["children"][0]["children"][0][
        "children"
    ][0]
    assert leaf["canonicalId"] == "m.num.count.1_100"
    assert leaf["status"] == "draft"
    assert leaf["children"] == []


def test_admin_contract_crud_and_relation_groups(client):
    group = seed_group(client)
    created = admin_post(
        client,
        "/api/v1/admin/knowledge",
        {
            "canonicalId": "m.num.count.1_100",
            "groupNodeId": group,
            "knowledgeName": "100以内数数",
            "knowledgeType": "skill",
            "gradeTerm": "一年级上册",
            "scope": "core",
            "cognitiveLevel": "remember",
            "importance": "core",
            "aliases": ["数数"],
            "coreKeywords": ["数到100"],
        },
    )
    assert created["aliases"] == ["数数"]
    assert created["rowVersion"] == 1
    patched = client.patch(
        "/api/v1/admin/knowledge/m.num.count.1_100",
        json={"knowledgeName": "100以内顺数", "rowVersion": 1},
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["rowVersion"] == 2
    stale = client.patch(
        "/api/v1/admin/knowledge/m.num.count.1_100",
        json={"knowledgeName": "过期修改", "rowVersion": 1},
    )
    assert stale.status_code == 409
    tree = client.get("/api/v1/admin/catalog/tree").json()["data"]
    assert (
        tree[0]["children"][0]["children"][0]["children"][0]["children"][0]["level"]
        == 5
    )
    me = client.get(
        "/api/v1/admin/me",
        headers={"X-Admin-User": "editor-1", "X-Admin-Roles": "editor"},
    )
    assert me.status_code == 200
    assert "release:publish" not in me.json()["data"]["permissions"]

    admin_post(
        client,
        "/api/v1/admin/knowledge",
        {
            "canonicalId": "m.num.write.1_100",
            "groupNodeId": group,
            "knowledgeName": "100以内写数",
            "knowledgeType": "skill",
            "gradeTerm": "一年级上册",
            "scope": "core",
            "cognitiveLevel": "understand",
            "importance": "important",
        },
    )
    relation = client.post(
        "/api/v1/admin/relations/batch",
        json={
            "operations": [
                {
                    "operation": "add",
                    "fromCanonicalId": "m.num.count.1_100",
                    "toCanonicalId": "m.num.write.1_100",
                    "relationType": "prerequisite",
                }
            ]
        },
    )
    assert relation.status_code == 200
    groups = client.get("/api/v1/admin/relations/m.num.write.1_100")
    assert groups.json()["data"]["prerequisites"] == ["m.num.count.1_100"]
    relation_page = client.get(
        "/api/v1/admin/relations/m.num.write.1_100",
        params={"group": "prerequisites", "pageNum": 1, "pageSize": 20},
    ).json()["data"]
    assert relation_page["total"] == 1
    assert relation_page["list"] == ["m.num.count.1_100"]

    knowledge_page = client.get(
        "/api/v1/admin/knowledge",
        params={"groupNodeId": group, "pageNum": 2, "pageSize": 1},
    ).json()["data"]
    assert knowledge_page["total"] == 2
    assert len(knowledge_page["list"]) == 1
    search_page = client.get(
        "/api/v1/admin/knowledge",
        params={"keyword": "数数", "pageNum": 1, "pageSize": 20},
    ).json()["data"]
    assert search_page["total"] == 1
    assert search_page["list"][0]["canonicalId"] == "m.num.count.1_100"


def test_admin_release_changes_and_audit_logs(client):
    seed_group(client)

    changes = client.get("/api/v1/admin/release-changes")
    assert changes.status_code == 200
    assert changes.json()["data"][0]["entityType"] == "catalog_node"

    first_page = client.get(
        "/api/v1/admin/audit-logs", params={"pageNum": 1, "pageSize": 2}
    )
    second_page = client.get(
        "/api/v1/admin/audit-logs", params={"pageNum": 2, "pageSize": 2}
    )
    assert first_page.status_code == 200
    first_data = first_page.json()["data"]
    second_data = second_page.json()["data"]
    assert first_data["total"] == 4
    assert first_data["pageSize"] == 2
    assert len(first_data["list"]) == 2
    assert first_data["list"][0]["actorType"] == "admin"
    assert first_data["list"][0]["resourceType"] == "catalog_node"
    assert {item["id"] for item in first_data["list"]}.isdisjoint(
        {item["id"] for item in second_data["list"]}
    )


def test_admin_import_prevalidates_xlsx(client):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "knowledge_points"
    sheet.append(
        [
            "canonical_id",
            "type",
            "name",
            "grade_term",
            "scope",
            "pep24_path",
            "ocr_signals",
            "exercise_signature",
            "prerequisites",
        ]
    )
    sheet.append(
        [
            "m.num.count.1_100",
            "skill",
            "100以内数数",
            "一年级上册",
            "core",
            "一上/数的认识",
            '["数到100"]',
            None,
            "[]",
        ]
    )
    content = BytesIO()
    workbook.save(content)

    response = client.post(
        "/api/v1/admin/imports",
        files={
            "file": (
                "knowledge.xlsx",
                content.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    job = response.json()["data"]
    assert job["status"] == "success"
    assert job["totalCount"] == 1
    assert job["errorCount"] == 0
    assert client.get(f"/api/v1/admin/jobs/{job['jobId']}").json()["data"] == job
    errors = client.get(
        f"/api/v1/admin/jobs/{job['jobId']}/errors",
        params={"pageNum": 1, "pageSize": 20},
    ).json()["data"]
    assert errors["total"] == 0
    assert errors["list"] == []

    committed = client.post(f"/api/v1/admin/imports/{job['jobId']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["data"]["committed"] is True
    knowledge = client.get("/api/v1/admin/knowledge/m.num.count.1_100").json()["data"]
    assert knowledge["knowledgeName"] == "100以内数数"
    assert knowledge["textbookMappings"][0]["textbookPath"] == "一上/数的认识"


def test_publish_validation_blocks_missing_textbook_mapping(client):
    group = seed_group(client)
    admin_post(
        client,
        "/api/v1/admin/knowledge",
        {
            "canonicalId": "m.shape.solid.cuboid",
            "groupNodeId": group,
            "knowledgeName": "长方体",
            "knowledgeType": "concept",
            "gradeTerm": "一年级上册",
            "scope": "core",
            "cognitiveLevel": "remember",
            "importance": "core",
        },
    )
    batch = admin_post(
        client,
        "/api/v1/admin/release-batches",
        {"versionLabel": "2026.08.04.invalid"},
    )
    response = client.post(f"/api/v1/admin/release-batches/{batch['id']}/validate")
    assert response.status_code == 200
    assert response.json()["data"]["passed"] is False
    assert "教材映射" in response.json()["data"]["errors"][0]["reason"]


def test_hmac_nonce_cannot_be_replayed(client):
    seed_release(client)
    headers = open_headers(client)
    assert client.get("/api/v1/open/knowledge/tree", headers=headers).status_code == 200
    replay = client.get("/api/v1/open/knowledge/tree", headers=headers)
    assert replay.status_code == 401
    assert replay.json()["code"] == "AUTH_FAILED"


def test_open_scope_is_required(client):
    response = client.get(
        "/api/v1/open/knowledge/tree",
        headers=open_headers(client, "app_without_read", allowed_scopes=["write"]),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
