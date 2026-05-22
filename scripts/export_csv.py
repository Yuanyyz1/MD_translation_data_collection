import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.crud import get_submitted_export_rows
from backend.database import Base, SessionLocal, engine


DEFAULT_OUTPUT = "submitted_export.csv"


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_OUTPUT)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        rows = get_submitted_export_rows(db)
    finally:
        db.close()

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dataset_name",
                "conversation_id",
                "turn_id",
                "speaker",
                "doctor_email",
                "english_text",
                "chinese_text",
                "translated_text_edited",
                "submitted_at",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} submitted rows to {output_path}")


if __name__ == "__main__":
    main()
