from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from backend.database import SessionLocal
from backend.models import User

BASE_URL = "http://127.0.0.1:8000"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "ACCESS_LINKS.md"


def write_access_links_markdown() -> Path:
    db = SessionLocal()
    try:
        users = db.scalars(select(User).order_by(User.role.asc(), User.email.asc())).all()
    finally:
        db.close()

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "# Access Links Registry",
        "",
        f"Auto-generated at: {now_utc}",
        "",
        "| Role | Person (Email) | Link |",
        "|---|---|---|",
    ]

    if not users:
        lines.append("| - | - | No users found |")
    else:
        for user in users:
            if user.role == "admin":
                link = f"{BASE_URL}/admin/{user.access_token}/upload"
            elif user.role == "health_professional":
                link = f"{BASE_URL}/health-professional/{user.access_token}/tasks"
            else:
                link = "(unsupported role)"
            lines.append(f"| {user.role} | {user.email} | `{link}` |")

    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OUTPUT_PATH
