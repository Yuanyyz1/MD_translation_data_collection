import sys
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from backend.auth import hash_password
from backend.database import Base, SessionLocal, engine
from backend.models import User
from scripts.access_links_registry import write_access_links_markdown


ADMIN_EMAIL = "admin@example.com"
DOCTOR_EMAIL = "doctor@example.com"
PLACEHOLDER_PASSWORD = "link-only-auth-disabled"


def upsert_user(email: str, role: str) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.role = role
            if not user.access_token:
                user.access_token = secrets.token_urlsafe(16)
        else:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(PLACEHOLDER_PASSWORD),
                    role=role,
                    access_token=secrets.token_urlsafe(16),
                )
            )
        db.commit()
    finally:
        db.close()


def main() -> None:
    Base.metadata.create_all(bind=engine)
    upsert_user(ADMIN_EMAIL, "admin")
    upsert_user(DOCTOR_EMAIL, "doctor")

    db = SessionLocal()
    try:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        doctor = db.scalar(select(User).where(User.email == DOCTOR_EMAIL))
    finally:
        db.close()

    print("Seed complete.")
    if admin:
        print(f"Admin link: http://127.0.0.1:8000/admin/{admin.access_token}/upload")
    if doctor:
        print(f"Doctor link: http://127.0.0.1:8000/doctor/{doctor.access_token}/tasks")
    output_path = write_access_links_markdown()
    print(f"Access registry updated: {output_path}")
    print("You can also open http://127.0.0.1:8000/ to view all local access links.")


if __name__ == "__main__":
    main()
