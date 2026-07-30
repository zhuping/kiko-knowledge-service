def test_health_and_admin_identity(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.json()["data"]["status"] == "ok"
    assert client.get("/health/ready").json()["data"]["database"] == "ok"
    identity = client.get(
        "/api/v1/admin/me",
        headers={"X-Admin-Subject": "editor", "X-Admin-Roles": "editor"},
    ).json()["data"]
    assert identity == {"subject": "editor", "roles": ["editor"]}


def test_release_is_immutable_and_clones_stable_ids(client, seeded, editor_headers):
    package_id = seeded["package"]["id"]
    version_id = seeded["version"]["id"]
    immutable = client.post(
        f"/api/v1/admin/packages/{package_id}/versions/{version_id}/catalog",
        headers=editor_headers,
        json={
            "node_type": "unit",
            "code": "U3",
            "name": "不可写",
            "order_no": 3,
        },
    )
    assert immutable.status_code == 409
    assert immutable.json()["error"]["code"] == "PACKAGE_VERSION_IMMUTABLE"

    created = client.post(
        f"/api/v1/admin/packages/{package_id}/versions",
        headers=editor_headers,
        json={
            "version": "1.1.0",
            "based_on_version_id": version_id,
            "release_notes": "克隆测试",
        },
    )
    assert created.status_code == 201, created.text
    clone_id = created.json()["data"]["id"]
    original = client.get(
        f"/api/v1/admin/packages/{package_id}/versions/{version_id}/catalog",
        headers=editor_headers,
    ).json()["data"]
    cloned = client.get(
        f"/api/v1/admin/packages/{package_id}/versions/{clone_id}/catalog",
        headers=editor_headers,
    ).json()["data"]
    assert {item["logical_id"] for item in original} == {
        item["logical_id"] for item in cloned
    }
    assert {item["id"] for item in original}.isdisjoint({item["id"] for item in cloned})

    node = cloned[0]
    changed = client.patch(
        f"/api/v1/admin/packages/{package_id}/versions/{clone_id}/catalog/{node['id']}",
        headers=editor_headers,
        json={"name": "新名称", "lock_version": node["lock_version"]},
    )
    assert changed.status_code == 200
    conflict = client.patch(
        f"/api/v1/admin/packages/{package_id}/versions/{clone_id}/catalog/{node['id']}",
        headers=editor_headers,
        json={"name": "覆盖", "lock_version": node["lock_version"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "EDIT_CONFLICT"


def test_relation_cycle_and_export(client, seeded, editor_headers):
    package_id = seeded["package"]["id"]
    version_id = seeded["version"]["id"]
    clone = client.post(
        f"/api/v1/admin/packages/{package_id}/versions",
        headers=editor_headers,
        json={"version": "2.0.0", "based_on_version_id": version_id},
    ).json()["data"]
    objectives = client.get(
        f"/api/v1/admin/packages/{package_id}/versions/{clone['id']}/objectives",
        headers=editor_headers,
    ).json()["data"]
    by_code = {item["code"]: item for item in objectives}
    response = client.post(
        f"/api/v1/admin/packages/{package_id}/versions/{clone['id']}/relations",
        headers=editor_headers,
        json={
            "source_objective_id": by_code["SUB-5"]["id"],
            "target_objective_id": by_code["ADD-5"]["id"],
            "relation_type": "prerequisite_of",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OBJECTIVE_RELATION_CYCLE"

    exported = client.get(
        f"/api/v1/admin/packages/{package_id}/versions/{version_id}/export",
        headers=editor_headers,
    )
    assert exported.status_code == 200
    data = exported.json()["data"]
    assert data["version"] == "1.0.0"
    assert len(data["content_hash"]) == 64
    assert data["exemplars"][0]["question_text"] is None


def test_empty_release_fails_validation(client, editor_headers):
    created = client.post(
        "/api/v1/admin/packages",
        headers=editor_headers,
        json={
            "code": "EMPTY",
            "subject_code": "math",
            "grade": 2,
            "semester": "upper",
            "edition": "test",
        },
    ).json()["data"]
    package_id = created["package"]["id"]
    version_id = created["version"]["id"]
    response = client.post(
        f"/api/v1/admin/packages/{package_id}/versions/{version_id}/submit-review",
        headers=editor_headers,
    )
    assert response.status_code == 422
    codes = {item["code"] for item in response.json()["error"]["details"]["errors"]}
    assert {"CATALOG_EMPTY", "OBJECTIVES_EMPTY"} <= codes


def test_request_validation_and_permissions(client, seeded):
    response = client.post(
        "/api/v1/admin/packages",
        headers={"X-Admin-Subject": "viewer", "X-Admin-Roles": "viewer"},
        json={
            "code": "NOPE",
            "subject_code": "math",
            "grade": 1,
            "semester": "upper",
            "edition": "test",
        },
    )
    assert response.status_code == 403
    invalid = client.post(
        "/api/v1/admin/packages",
        json={"code": "", "grade": 0},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_REQUEST"
