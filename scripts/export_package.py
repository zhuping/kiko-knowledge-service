import argparse
import json
from pathlib import Path

from app.core.database import SessionLocal
from app.domains.catalog.import_export import export_version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version_id")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with SessionLocal() as db:
        data = export_version(db, args.version_id)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
