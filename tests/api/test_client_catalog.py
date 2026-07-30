def test_client_catalog_is_authorized_and_copyright_filtered(client, seeded):
    auth = seeded["auth"]
    packages = client.get("/api/v1/packages", headers=auth)
    assert packages.status_code == 200
    assert [item["id"] for item in packages.json()["data"]] == [seeded["package"]["id"]]
    package = client.get(f"/api/v1/packages/{seeded['package']['id']}", headers=auth)
    assert package.json()["data"]["current_release"]["version"] == "1.0.0"

    logical_id = seeded["objectives"][0]["logical_id"]
    objective = client.get(f"/api/v1/objectives/{logical_id}", headers=auth)
    assert objective.status_code == 200
    assert objective.json()["data"]["external_mappings"] == {
        "kiko-current-product": "legacy-add-5"
    }
    exemplars = client.get(
        f"/api/v1/objectives/{logical_id}/exemplars", headers=auth
    ).json()["data"]
    assert exemplars[0]["display_level"] == "reference"
    assert exemplars[0]["question_text"] is None
    assert exemplars[0]["answer"] is None


def test_invalid_api_key_is_rejected(client):
    missing = client.get("/api/v1/packages")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "INVALID_API_KEY"
    invalid = client.get(
        "/api/v1/packages",
        headers={"Authorization": "Bearer kh_live_unknown.short"},
    )
    assert invalid.status_code == 401


def test_key_rotation_and_disable(client, seeded, admin_headers):
    client_id = seeded["client_app"]["id"]
    old_auth = seeded["auth"]
    rotated = client.post(
        f"/api/v1/admin/client-apps/{client_id}/rotate-key",
        headers=admin_headers,
    )
    assert rotated.status_code == 200
    new_auth = {"Authorization": f"Bearer {rotated.json()['data']['api_key']}"}
    assert client.get("/api/v1/packages", headers=old_auth).status_code == 401
    assert client.get("/api/v1/packages", headers=new_auth).status_code == 200
    assert (
        client.post(
            f"/api/v1/admin/client-apps/{client_id}/disable",
            headers=admin_headers,
        ).status_code
        == 200
    )
    assert client.get("/api/v1/packages", headers=new_auth).status_code == 401
    assert (
        client.post(
            f"/api/v1/admin/client-apps/{client_id}/enable",
            headers=admin_headers,
        ).status_code
        == 200
    )
