import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client() -> TestClient:
    app = create_app("sqlite+pysqlite:///:memory:", create_schema=True)
    app.state.settings.api_secret_key = Fernet.generate_key().decode()
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/admin/login",
            json={"username": "无问", "password": "Kiko123!@#"},
        )
        assert response.status_code == 200, response.text
        yield test_client
