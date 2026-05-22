import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from backend.database import Base, SessionLocal, engine
from backend.models import User

BASE_URL = "http://127.0.0.1:8000"


def main() -> None:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        health_professionals = db.scalars(select(User).where(User.role == "health_professional").order_by(User.email.asc())).all()
        if not health_professionals:
            print("No health_professional users found.")
            return
        for health_professional in health_professionals:
            print(f"{health_professional.email} -> {BASE_URL}/health-professional/{health_professional.access_token}/tasks")
    finally:
        db.close()


if __name__ == "__main__":
    main()
