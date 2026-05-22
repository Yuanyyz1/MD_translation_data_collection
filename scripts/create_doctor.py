import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from backend.auth import hash_password
from backend.database import Base, SessionLocal, engine
from backend.models import User
from scripts.access_links_registry import write_access_links_markdown

PLACEHOLDER_PASSWORD = "link-only-auth-disabled"
BASE_URL = "http://127.0.0.1:8000"


def create_or_get_doctor(email: str) -> User:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.role = "doctor"
            if not user.access_token:
                user.access_token = secrets.token_urlsafe(16)
        else:
            user = User(
                email=email,
                password_hash=hash_password(PLACEHOLDER_PASSWORD),
                role="doctor",
                access_token=secrets.token_urlsafe(16),
            )
            db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/create_doctor.py doctor1@example.com [doctor2@example.com ...]")
        raise SystemExit(1)

    Base.metadata.create_all(bind=engine)

    for raw_email in sys.argv[1:]:
        email = raw_email.strip().lower()
        if not email:
            continue
        user = create_or_get_doctor(email)
        print(f"{email} -> {BASE_URL}/doctor/{user.access_token}/tasks")

    output_path = write_access_links_markdown()
    print(f"Access registry updated: {output_path}")


if __name__ == "__main__":
    main()
