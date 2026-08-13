def test_admin_login_accepts_only_the_hardcoded_account(client):
    client.cookies.clear()

    wrong = client.post(
        "/api/v1/admin/login",
        json={"username": "无问", "password": "wrong"},
    )
    assert wrong.status_code == 401
    assert client.get("/api/v1/admin/me").status_code == 401

    login = client.post(
        "/api/v1/admin/login",
        json={"username": "无问", "password": "Kiko123!@#"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["roles"] == ["admin"]
    assert client.get("/api/v1/admin/me").status_code == 200

    assert client.post("/api/v1/admin/logout").status_code == 200
    assert client.get("/api/v1/admin/me").status_code == 401
