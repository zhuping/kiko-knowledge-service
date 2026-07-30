import os
import subprocess

import pytest


@pytest.mark.mysql
def test_mysql_migrations_upgrade_to_head():
    database_url = os.getenv("KIKO_KNOWLEDGE_TEST_MYSQL_URL")
    if not database_url:
        pytest.skip("KIKO_KNOWLEDGE_TEST_MYSQL_URL is not configured")
    environment = {
        **os.environ,
        "KIKO_KNOWLEDGE_ENVIRONMENT": "development",
        "KIKO_KNOWLEDGE_DATABASE_URL": database_url,
    }
    subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )
    subprocess.run(
        ["python3", "-m", "alembic", "check"],
        check=True,
        env=environment,
    )
