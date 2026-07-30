import argparse
from pathlib import Path

from app.core.database import SessionLocal
from app.core.security import AdminContext
from app.domains.catalog.import_export import confirm_import, preview_import
from app.schemas.admin import ImportCreate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version_id")
    parser.add_argument("file", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    data = ImportCreate(
        format=args.file.suffix.removeprefix(".").lower(),
        content=args.file.read_text(encoding="utf-8"),
    )
    actor = AdminContext("import-script", frozenset({("admin", None)}))
    with SessionLocal() as db:
        job = preview_import(db, actor, args.version_id, data)
        if args.confirm and job.status == "validated":
            job = confirm_import(db, actor, job.id)
        print(job.id, job.status, job.preview_json, job.errors_json)


if __name__ == "__main__":
    main()
