import json
from pathlib import Path

from app.main import app


def main() -> None:
    target = Path("openapi/knowledge-service.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
