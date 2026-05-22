import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import Base, engine
from scripts.access_links_registry import write_access_links_markdown


def main() -> None:
    Base.metadata.create_all(bind=engine)
    output_path = write_access_links_markdown()
    print(f"Access registry updated: {output_path}")


if __name__ == "__main__":
    main()
