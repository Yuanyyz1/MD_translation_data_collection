import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.crud import upsert_conversations_from_rows
from backend.database import Base, SessionLocal, engine


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/import_csv.py <dataset_name> <path_to_csv>")
        raise SystemExit(1)

    dataset_name = sys.argv[1].strip()
    if not dataset_name:
        print("Dataset name is required.")
        raise SystemExit(1)

    csv_path = Path(sys.argv[2])
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        raise SystemExit(1)

    Base.metadata.create_all(bind=engine)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"conversation_id", "turn_id", "speaker", "english_text", "chinese_text"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            print("CSV missing required columns: conversation_id, turn_id, speaker, english_text, chinese_text")
            raise SystemExit(1)
        rows = list(reader)

    db = SessionLocal()
    try:
        inserted, updated = upsert_conversations_from_rows(db, rows, dataset_name)
        print(f"Import complete for dataset '{dataset_name}'. Inserted={inserted}, Updated={updated}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
