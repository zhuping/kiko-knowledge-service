from __future__ import annotations

import base64
import hashlib
import hmac
import time
from io import BytesIO

from cryptography.fernet import Fernet
from openpyxl import Workbook
from sqlalchemy import select

from app.models import ApiClient, CatalogNode, TextbookEdition


def call(client, method: str, path: str, payload: dict | None = None, **kwargs):
    response = client.request(method, path, json=payload, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def seed_catalog(client):
    kb = call(
        client,
        "POST",
        "/api/v1/admin/knowledge-bases",
        {
            "name": "人教版2024数学一年级上册",
            "gradeTermCode": "g1_t1",
            "subjectCode": "math",
            "textbookEditionCode": "pep_math_2024_g1_t1",
        },
    )
    with client.app.state.session_factory() as session:
        edition = session.scalar(
            select(TextbookEdition).where(
                TextbookEdition.edition_code == "pep_math_2024_g1_t1"
            )
        )
        node = CatalogNode(
            edition_id=edition.id,
            level=1,
            node_type="unit",
            source_key="unit_1",
            source_path="第一单元/数的认识",
            title="数的认识",
            sort_order=1,
        )
        session.add(node)
        session.commit()
        node_id = node.id
    return kb, node_id


def create_point(client, canonical_id: str, name: str):
    return call(
        client,
        "POST",
        "/api/v1/admin/knowledge",
        {
            "canonicalId": canonical_id,
            "knowledgeName": name,
            "knowledgeType": "skill",
            "gradeTermCode": "g1_t1",
            "scope": "core",
            "ocrSignals": [name],
            "exerciseSignature": "基础题型",
        },
    )


def map_point(client, kb: dict, node_id: int, canonical_id: str):
    return call(
        client,
        "POST",
        f"/api/v1/admin/knowledge-bases/{kb['id']}/mappings",
        {
            "catalogNodeId": node_id,
            "canonicalId": canonical_id,
            "rowVersion": kb["rowVersion"],
        },
    )


def publish(client, kb_id: str):
    return call(client, "POST", f"/api/v1/admin/knowledge-bases/{kb_id}/publish")


def open_headers(client, path: str, query: str = "", secret: bytes = b"secret"):
    request_path, embedded_query = (path.split("?", 1) + [""])[:2]
    if embedded_query and not query:
        query = embedded_query
    with client.app.state.session_factory() as session:
        client_row = session.scalar(
            select(ApiClient).where(ApiClient.app_key == "app_test")
        )
        if client_row is None:
            session.add(
                ApiClient(
                    app_key="app_test",
                    secret_ciphertext=Fernet(
                        client.app.state.settings.api_secret_key.encode()
                    )
                    .encrypt(secret)
                    .decode(),
                    allowed_scopes=["read"],
                )
            )
        session.commit()
    timestamp = str(int(time.time()))
    nonce = f"nonce-{time.time_ns()}"
    empty_hash = hashlib.sha256(b"").hexdigest()
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    canonical = "\n".join(
        ["GET", request_path, query_hash, empty_hash, timestamp, nonce]
    ).encode()
    signature = base64.b64encode(
        hmac.new(secret, canonical, hashlib.sha256).digest()
    ).decode()
    return {
        "X-App-Key": "app_test",
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


def test_publish_snapshot_and_point_revision(client):
    kb, node_id = seed_catalog(client)
    create_point(client, "10000001", "100以内数数")
    create_point(client, "10000002", "100以内写数")
    map_point(client, kb, node_id, "10000001")
    kb = call(client, "GET", f"/api/v1/admin/knowledge-bases/{kb['id']}")
    map_point(client, kb, node_id, "10000002")
    knowledge_page = call(
        client,
        "GET",
        "/api/v1/admin/knowledge",
        params={"canonicalId": "10000001"},
    )
    assert knowledge_page["list"][0]["knowledgeBaseMappings"] == [
        {
            "knowledgeBaseId": kb["id"],
            "knowledgeBaseName": "人教版2024数学一年级上册",
            "textbookEditionCode": "pep_math_2024_g1_t1",
            "textbookEditionName": "人教版2024数学一年级上册",
        }
    ]
    call(
        client,
        "POST",
        "/api/v1/admin/relations",
        {
            "canonicalId": "10000002",
            "prerequisiteCanonicalIds": ["10000001"],
        },
    )
    assert call(
        client,
        "POST",
        f"/api/v1/admin/knowledge-bases/{kb['id']}/publish:validate",
    )["passed"]
    release = publish(client, kb["id"])
    detail = client.get(
        f"/api/v1/admin/knowledge-bases/{kb['id']}/releases/{release['releaseVersion']}"
    )
    assert detail.status_code == 200, detail.text
    point = call(client, "GET", "/api/v1/admin/knowledge/10000001")
    assert point["status"] == "published"
    relations = call(client, "GET", "/api/v1/admin/relations")
    assert relations["list"][1]["status"] == "published"
    assert relations["list"][1]["prerequisites"] == [
        {"canonicalId": "10000001", "knowledgeName": "100以内数数"}
    ]

    path = f"/api/v1/open/knowledge-bases/{kb['id']}/content"
    response = client.get(path, headers=open_headers(client, path))
    assert response.status_code == 200
    data = response.json()["data"]
    assert response.json()["meta"]["releaseVersion"] == release["releaseVersion"]
    assert data["knowledgeBaseName"] == "人教版2024数学一年级上册"
    assert data["gradeTermCode"] == "g1_t1"
    assert data["subjectCode"] == "math"
    assert data["contentHash"] == release["contentHash"]
    assert [mapping["sortOrder"] for mapping in data["mappings"]] == [1, 2]
    assert len(data["knowledge"]) == 2


def test_create_knowledge_generates_numeric_id(client):
    point = call(
        client,
        "POST",
        "/api/v1/admin/knowledge",
        {
            "knowledgeName": "自动生成 ID 的知识点",
            "knowledgeType": "concept",
            "gradeTermCode": "g1_t1",
            "scope": "core",
        },
    )
    assert point["canonicalId"].isdigit()
    assert len(point["canonicalId"]) == 8
    assert point["canonicalId"].startswith("1")


def test_edit_creates_pending_revision_until_next_release(client):
    kb, node_id = seed_catalog(client)
    create_point(client, "10000001", "100以内数数")
    map_point(client, kb, node_id, "10000001")
    first = publish(client, kb["id"])
    edited = call(
        client,
        "PATCH",
        "/api/v1/admin/knowledge/10000001",
        {"knowledgeName": "100以内顺数", "rowVersion": 1},
    )
    assert edited["status"] == "pending"
    assert edited["latestFormal"]["knowledgeName"] == "100以内数数"
    pending_kb = call(client, "GET", f"/api/v1/admin/knowledge-bases/{kb['id']}")
    assert pending_kb["status"] == "pending"
    assert pending_kb["recentPublishedAt"] == first["publishedAt"]
    assert pending_kb["updatedAt"] > pending_kb["recentPublishedAt"]
    list_path = "/api/v1/open/knowledge-bases"
    open_list = client.get(list_path, headers=open_headers(client, list_path)).json()[
        "data"
    ]
    assert [item["id"] for item in open_list["list"]] == [kb["id"]]
    assert open_list["list"][0]["name"] == "人教版2024数学一年级上册"
    assert open_list["list"][0]["status"] == "published"
    path = f"/api/v1/open/knowledge-bases/{kb['id']}/content"
    old = client.get(path, headers=open_headers(client, path)).json()["data"]
    assert old["knowledge"][0]["knowledgeName"] == "100以内数数"
    second = publish(client, kb["id"])
    assert second["versionNo"] == first["versionNo"] + 1
    diff = call(
        client,
        "GET",
        f"/api/v1/admin/knowledge-bases/{kb['id']}/releases/{second['releaseVersion']}/diff",
    )
    assert diff["baseReleaseVersion"] == first["releaseVersion"]
    assert diff["changed"] is True
    assert diff["summary"]["knowledge"]["modified"] == 1
    published_kb = call(client, "GET", f"/api/v1/admin/knowledge-bases/{kb['id']}")
    assert published_kb["recentPublishedAt"] == second["publishedAt"]
    current = call(client, "GET", "/api/v1/admin/knowledge/10000001")
    assert current["status"] == "published"
    assert (
        current["currentFormalVersions"][-1]["releaseVersion"]
        == second["releaseVersion"]
    )
    rolled_back = call(
        client,
        "POST",
        f"/api/v1/admin/knowledge-bases/{kb['id']}/releases/{first['releaseVersion']}:rollback",
        {"reason": "恢复首个正式版本"},
    )
    assert rolled_back["releaseType"] == "rollback"
    assert (
        call(client, "GET", f"/api/v1/admin/knowledge-bases/{kb['id']}")[
            "currentReleaseVersion"
        ]
        == rolled_back["releaseVersion"]
    )


def test_release_includes_external_prerequisite(client):
    kb, node_id = seed_catalog(client)
    create_point(client, "10000001", "前置知识点")
    create_point(client, "10000002", "当前知识点")
    map_point(client, kb, node_id, "10000002")
    call(
        client,
        "POST",
        "/api/v1/admin/relations",
        {
            "canonicalId": "10000002",
            "prerequisiteCanonicalIds": ["10000001"],
        },
    )
    release = publish(client, kb["id"])
    path = f"/api/v1/open/knowledge-bases/{kb['id']}/content"
    data = client.get(path, headers=open_headers(client, path)).json()["data"]
    assert data["releaseVersion"] == release["releaseVersion"]
    assert data["relations"] == [
        {
            "relationType": "prerequisite",
            "fromCanonicalId": "10000001",
            "toCanonicalId": "10000002",
            "note": None,
        }
    ]


def test_relation_draft_can_be_reverted(client):
    kb, node_id = seed_catalog(client)
    create_point(client, "10000001", "100以内数数")
    create_point(client, "10000002", "100以内写数")
    map_point(client, kb, node_id, "10000001")
    kb = call(client, "GET", f"/api/v1/admin/knowledge-bases/{kb['id']}")
    map_point(client, kb, node_id, "10000002")
    relation = call(
        client,
        "POST",
        "/api/v1/admin/relations",
        {
            "canonicalId": "10000002",
            "prerequisiteCanonicalIds": ["10000001"],
        },
    )[0]
    publish(client, kb["id"])
    changed = call(
        client,
        "PATCH",
        f"/api/v1/admin/relations/{relation['relationId']}",
        {"operation": "upsert", "note": "补充说明", "rowVersion": 1},
    )
    assert changed["status"] == "pending"
    restored = call(
        client,
        "POST",
        f"/api/v1/admin/relations/{relation['relationId']}/draft:revert",
    )
    assert restored["status"] == "published"
    removed = client.delete(
        f"/api/v1/admin/relations/{relation['relationId']}",
        params={"rowVersion": restored["rowVersion"]},
    )
    assert removed.status_code == 200, removed.text
    target = call(
        client,
        "GET",
        "/api/v1/admin/relations",
        params={"canonicalId": "10000002"},
    )
    assert target["list"][0]["status"] == "pending"
    call(
        client,
        "POST",
        f"/api/v1/admin/relations/{relation['relationId']}/draft:revert",
    )


def test_offline_blocks_default_open_read_but_keeps_history(client):
    kb, node_id = seed_catalog(client)
    create_point(client, "10000001", "100以内数数")
    map_point(client, kb, node_id, "10000001")
    release = publish(client, kb["id"])
    call(client, "POST", f"/api/v1/admin/knowledge-bases/{kb['id']}/offline")
    path = f"/api/v1/open/knowledge-bases/{kb['id']}/content"
    headers = open_headers(client, path)
    assert client.get(path, headers=headers).status_code == 404
    query = f"releaseVersion={release['releaseVersion']}"
    historical_path = f"{path}?{query}"
    assert (
        client.get(
            historical_path,
            headers=open_headers(client, historical_path, query),
        ).status_code
        == 200
    )


def test_import_uses_current_excel_fields_and_creates_prerequisite(client):
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
            "10000001",
            "skill",
            "100以内数数",
            "一年级上册",
            "core",
            "一上/数的认识",
            '["数到100"]',
            "数数题",
            "[]",
        ]
    )
    sheet.append(
        [
            "10000002",
            "skill",
            "100以内写数",
            "一年级上册",
            "core",
            "一上/数的认识",
            '["写数"]',
            "写数题",
            '["10000001"]',
        ]
    )
    content = BytesIO()
    workbook.save(content)
    response = client.post(
        "/api/v1/admin/imports",
        files={"file": ("knowledge.xlsx", content.getvalue(), "application/xlsx")},
    )
    assert response.status_code == 200, response.text
    job = response.json()["data"]
    committed = client.post(f"/api/v1/admin/imports/{job['jobId']}/commit")
    assert committed.status_code == 200, committed.text
    point = call(client, "GET", "/api/v1/admin/knowledge/10000002")
    assert point["ocrSignals"] == ["写数"]
    relations = call(client, "GET", "/api/v1/admin/relations")
    target = next(row for row in relations["list"] if row["canonicalId"] == "10000002")
    assert target["prerequisites"] == [
        {"canonicalId": "10000001", "knowledgeName": "100以内数数"}
    ]


def test_v1_admin_identity_requires_the_login_session(client):
    client.cookies.clear()
    response = client.get("/api/v1/admin/me", headers={"X-Admin-Roles": "admin"})
    assert response.status_code == 401

    login = client.post(
        "/api/v1/admin/login",
        json={"username": "无问", "password": "Kiko123!@#"},
    )
    assert login.status_code == 200
    assert client.get("/api/v1/admin/me").json()["data"]["roles"] == ["admin"]
