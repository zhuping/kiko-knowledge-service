import argparse

from app.core.database import SessionLocal
from app.core.security import AdminContext
from app.domains.gold_regression.service import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version_id")
    args = parser.parse_args()
    actor = AdminContext("regression-script", frozenset({("admin", None)}))
    with SessionLocal() as db:
        result = run(db, actor, args.version_id)
        print(result.id, result.passed, result.metrics_json)


if __name__ == "__main__":
    main()
