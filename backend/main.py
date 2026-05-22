import csv
import base64
import io
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .auth import hash_password
from .crud import (
    clear_all_health_professional_tasks,
    clear_submitted_output,
    clear_uploaded_conversations,
    get_admin_metadata_rows,
    get_health_professional_dataset_export_rows,
    get_health_professional_progress_rows,
    get_uploaded_dataset_rows,
    get_or_create_submission,
    get_submitted_export_rows,
    delete_dataset_by_name,
    upsert_conversations_from_rows,
)
from .database import Base, engine, get_db
from .models import Annotation, Conversation, Submission, User
from .models import HealthProfessionalDatasetAssignment
from .schemas import AnnotationCreateRequest, SaveDraftRequest, SubmitRequest, WorkspaceScreenshotUploadRequest

BASE_DIR = Path(__file__).resolve().parent.parent
if (os.getenv("VERCEL") or "").strip() == "1":
    WORKSPACE_SCREENSHOT_DIR = Path("/tmp") / "workspace_screenshots"
else:
    WORKSPACE_SCREENSHOT_DIR = BASE_DIR / "workspace_screenshots"
WORKSPACE_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Bilingual Health Professional Annotation Prototype")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def template_response(name: str, context: dict, status_code: int = 200):
    request = context.get("request")
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=context,
        status_code=status_code,
    )


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        user_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        if "name" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN name TEXT DEFAULT ''"))
        if "professional_role" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN professional_role TEXT DEFAULT ''"))
        if "access_token" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN access_token TEXT"))
        conn.execute(text("UPDATE users SET role = 'health_professional' WHERE role = 'doctor'"))

        conversation_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(conversations)")).fetchall()}
        if "dataset_name" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN dataset_name TEXT DEFAULT 'default'"))
        if "source_filename" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN source_filename TEXT DEFAULT ''"))
        conn.execute(
            text(
                "UPDATE conversations "
                "SET dataset_name = 'default' "
                "WHERE dataset_name IS NULL OR dataset_name = ''"
            )
        )
        if "conversation_group_id" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN conversation_group_id TEXT DEFAULT ''"))
        conn.execute(
            text(
                "UPDATE conversations "
                "SET conversation_group_id = id "
                "WHERE conversation_group_id IS NULL OR conversation_group_id = ''"
            )
        )
        if "turn_id" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN turn_id TEXT DEFAULT ''"))
        if "speaker" not in conversation_columns:
            conn.execute(text("ALTER TABLE conversations ADD COLUMN speaker TEXT DEFAULT ''"))
        if "chinese_text" not in conversation_columns and "chinese_text_original" in conversation_columns:
            conn.execute(text("ALTER TABLE conversations RENAME COLUMN chinese_text_original TO chinese_text"))

        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(annotations)")).fetchall()}
        if "clinical_significance" not in columns:
            conn.execute(text("ALTER TABLE annotations ADD COLUMN clinical_significance INTEGER"))
        if "subtlety" not in columns:
            conn.execute(text("ALTER TABLE annotations ADD COLUMN subtlety INTEGER"))
        if "inserted_error_text" not in columns:
            conn.execute(text("ALTER TABLE annotations ADD COLUMN inserted_error_text TEXT DEFAULT ''"))
        if "original_text" not in columns:
            conn.execute(text("ALTER TABLE annotations ADD COLUMN original_text TEXT DEFAULT ''"))

        submission_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(submissions)")).fetchall()}
        if "health_professional_id" not in submission_columns and "doctor_id" in submission_columns:
            conn.execute(text("ALTER TABLE submissions RENAME COLUMN doctor_id TO health_professional_id"))
            submission_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(submissions)")).fetchall()}
        if "translated_text_edited" not in submission_columns and "chinese_text_edited" in submission_columns:
            conn.execute(text("ALTER TABLE submissions RENAME COLUMN chinese_text_edited TO translated_text_edited"))

        users = conn.execute(text("SELECT id, access_token FROM users")).fetchall()
        for user_id, token in users:
            if not token:
                conn.execute(
                    text("UPDATE users SET access_token = :token WHERE id = :id"),
                    {"token": secrets.token_urlsafe(16), "id": user_id},
                )


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def slugify_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return cleaned.strip("._-") or "default"


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def normalize_name(value: str) -> str:
    return (value or "").strip()


def normalize_professional_role(value: str) -> str:
    return (value or "").strip()


def get_health_professional_link_rows(db: Session) -> list[dict[str, str]]:
    users = db.scalars(
        select(User)
        .where(User.role == "health_professional")
        .order_by(User.email.asc())
    ).all()
    rows: list[dict[str, str]] = []
    for user in users:
        assignments = db.scalars(
            select(HealthProfessionalDatasetAssignment)
            .where(HealthProfessionalDatasetAssignment.health_professional_id == user.id)
            .order_by(HealthProfessionalDatasetAssignment.slot.asc())
        ).all()
        slot_map = {a.slot: a.dataset_name for a in assignments}
        submitted_dataset_details: list[dict[str, str | int | bool]] = []
        for slot in (1, 2):
            dataset_name = (slot_map.get(slot) or "").strip()
            if not dataset_name:
                continue

            conversation_ids = db.scalars(
                select(Conversation.id).where(Conversation.dataset_name == dataset_name)
            ).all()
            unique_conversation_ids = set(conversation_ids)
            total_turns = len(unique_conversation_ids)
            submitted_conversation_ids = set(
                db.scalars(
                    select(Submission.conversation_id).where(
                        Submission.health_professional_id == user.id,
                        Submission.status == "submitted",
                        Submission.conversation_id.in_(unique_conversation_ids),
                    )
                ).all()
            ) if unique_conversation_ids else set()
            submitted_turns = len(submitted_conversation_ids)
            completed = total_turns > 0 and submitted_turns == total_turns

            submitted_dataset_details.append(
                {
                    "dataset_name": dataset_name,
                    "submitted_turns": submitted_turns,
                    "total_turns": total_turns,
                    "completed": completed,
                }
            )

        rows.append(
            {
                "health_professional_name": (user.name or "").strip(),
                "health_professional_role": (user.professional_role or "").strip(),
                "health_professional_email": user.email,
                "assigned_dataset_1": slot_map.get(1, ""),
                "assigned_dataset_2": slot_map.get(2, ""),
                "submitted_dataset_details": submitted_dataset_details,
                "link_path": f"/health-professional/{user.access_token}/tasks",
                "link_full": f"http://127.0.0.1:8000/health-professional/{user.access_token}/tasks",
            }
        )
    return rows


def get_available_dataset_names(db: Session) -> list[str]:
    names = db.scalars(select(Conversation.dataset_name).distinct()).all()
    cleaned = sorted({(name or "").strip() for name in names if (name or "").strip()}, key=str.lower)
    return cleaned


def delete_health_professional_related_data(db: Session, user: User) -> dict[str, int]:
    submission_ids = db.scalars(
        select(Submission.id).where(Submission.health_professional_id == user.id)
    ).all()

    annotations_deleted = 0
    if submission_ids:
        annotations_deleted = db.query(Annotation).filter(
            Annotation.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)

    submissions_deleted = db.query(Submission).filter(
        Submission.health_professional_id == user.id
    ).delete(synchronize_session=False)

    db.delete(user)
    db.commit()

    # Remove any saved screenshots for this health professional.
    for pattern in (f"health_professional_{user.id}__dataset_*.png", f"doctor_{user.id}__dataset_*.png"):
        for screenshot in WORKSPACE_SCREENSHOT_DIR.glob(pattern):
            try:
                screenshot.unlink()
            except OSError:
                pass

    return {
        "annotations_deleted": int(annotations_deleted or 0),
        "submissions_deleted": int(submissions_deleted or 0),
    }


def get_workspace_screenshot_path(health_professional_id: int, dataset_name: str) -> Path:
    safe_dataset = slugify_filename_part(dataset_name)
    return WORKSPACE_SCREENSHOT_DIR / f"health_professional_{health_professional_id}__dataset_{safe_dataset}.png"


@app.get("/")
def root(request: Request, db: Session = Depends(get_db)):
    return template_response(
        "home.html",
        {
            "request": request,
            "current_user": None,
        },
    )


def require_user_by_token(db: Session, token: str, expected_role: str) -> User:
    user = db.scalar(select(User).where(User.access_token == token, User.role == expected_role))
    if not user:
        raise HTTPException(status_code=404, detail="Invalid access link")
    return user


@app.get("/health-professional/{token}/tasks")
def health_professional_tasks(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    assigned_datasets = db.scalars(
        select(HealthProfessionalDatasetAssignment.dataset_name)
        .where(HealthProfessionalDatasetAssignment.health_professional_id == current_user.id)
    ).all()
    assigned_set = {(name or "").strip() for name in assigned_datasets if (name or "").strip()}
    if assigned_set:
        conversations = db.scalars(
            select(Conversation).where(Conversation.dataset_name.in_(assigned_set))
        ).all()
    else:
        conversations = []
    submissions = db.scalars(select(Submission).where(Submission.health_professional_id == current_user.id)).all()
    submission_by_conv = {s.conversation_id: s for s in submissions}

    dataset_to_conversation_ids: dict[str, list[str]] = {}
    for conv in conversations:
        dataset = (conv.dataset_name or "default").strip() or "default"
        dataset_to_conversation_ids.setdefault(dataset, []).append(conv.id)

    dataset_rows = []
    for dataset_name in sorted(dataset_to_conversation_ids.keys(), key=lambda v: v.lower()):
        conv_ids = dataset_to_conversation_ids[dataset_name]
        submitted_count = 0
        draft_count = 0
        for conv_id in conv_ids:
            submission = submission_by_conv.get(conv_id)
            if not submission:
                continue
            if submission.status == "submitted":
                submitted_count += 1
            elif submission.status == "draft":
                draft_count += 1
        total_count = len(conv_ids)
        not_started_count = max(total_count - submitted_count - draft_count, 0)
        completion_rate = (submitted_count / total_count * 100.0) if total_count > 0 else 0.0
        dataset_rows.append(
            {
                "dataset_name": dataset_name,
                "total_count": total_count,
                "submitted_count": submitted_count,
                "draft_count": draft_count,
                "not_started_count": not_started_count,
                "completion_rate": f"{completion_rate:.1f}%",
            }
        )

    return template_response(
        "health_professional_datasets.html",
        {"request": request, "current_user": current_user, "dataset_rows": dataset_rows, "access_token": token},
    )


@app.get("/health-professional/{token}/tasks/{dataset_name}")
def health_professional_tasks_for_dataset(
    token: str,
    dataset_name: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    assigned_datasets = db.scalars(
        select(HealthProfessionalDatasetAssignment.dataset_name)
        .where(HealthProfessionalDatasetAssignment.health_professional_id == current_user.id)
    ).all()
    assigned_set = {(name or "").strip() for name in assigned_datasets if (name or "").strip()}
    if assigned_set and dataset_name not in assigned_set:
        raise HTTPException(status_code=404, detail="Dataset not assigned to this health professional")
    conversations = db.scalars(select(Conversation).where(Conversation.dataset_name == dataset_name)).all()
    submissions = db.scalars(select(Submission).where(Submission.health_professional_id == current_user.id)).all()
    submission_by_conv = {s.conversation_id: s for s in submissions}

    def turn_sort_key(conv: Conversation):
        group_id = (conv.conversation_group_id or conv.id).strip().lower()
        raw = (conv.turn_id or "").strip()
        if not raw:
            return (group_id, 2, "", conv.id)
        if raw.isdigit():
            return (group_id, 0, int(raw), conv.id)
        match = re.match(r"^(\d+)", raw)
        if match:
            return (group_id, 1, int(match.group(1)), raw, conv.id)
        return (group_id, 2, raw.lower(), conv.id)

    conversations = sorted(conversations, key=turn_sort_key)

    task_rows = []
    for conv in conversations:
        submission = submission_by_conv.get(conv.id)
        task_rows.append(
            {
                "conversation": conv,
                "status": submission.status if submission else "not started",
                "last_saved_at": submission.last_saved_at if submission else None,
                "submitted_at": submission.submitted_at if submission else None,
                "consent_confirmed": submission.consent_confirmed if submission else False,
                "translated_text_edited": submission.translated_text_edited if submission else conv.chinese_text,
            }
        )

    def speaker_category(speaker: str) -> str:
        speaker_value = (speaker or "").strip().lower()
        if any(label in speaker_value for label in ("pharmacist", "doctor", "health professional", "health_professional", "clinician", "provider", "nurse")):
            return "clinician"
        if any(label in speaker_value for label in ("patient", "caregiver", "carer", "family")):
            return "patient"
        return "other"

    conversation_groups = []
    current_group_key = None
    current_group = None

    for row in task_rows:
        conv = row["conversation"]
        group_key = (conv.conversation_group_id or conv.id).strip() or conv.id
        if group_key != current_group_key:
            current_group = {"group_id": group_key, "turns": []}
            conversation_groups.append(current_group)
            current_group_key = group_key
        row["speaker_category"] = speaker_category(conv.speaker)
        current_group["turns"].append(row)

    return template_response(
        "health_professional_tasks.html",
        {
            "request": request,
            "current_user": current_user,
            "conversation_groups": conversation_groups,
            "access_token": token,
            "selected_dataset_name": dataset_name,
        },
    )


@app.post("/health-professional/{token}/workspace-screenshot")
def upload_workspace_screenshot(
    token: str,
    payload: WorkspaceScreenshotUploadRequest,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    dataset_name = (payload.dataset_name or "").strip()
    if not dataset_name:
        return JSONResponse({"ok": False, "error": "Dataset name is required."}, status_code=400)

    image_base64 = (payload.image_base64 or "").strip()
    if image_base64.startswith("data:image/png;base64,"):
        image_base64 = image_base64.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(image_base64, validate=True)
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid screenshot payload."}, status_code=400)

    if not image_bytes:
        return JSONResponse({"ok": False, "error": "Screenshot image is empty."}, status_code=400)

    output_path = get_workspace_screenshot_path(current_user.id, dataset_name)
    output_path.write_bytes(image_bytes)
    return {"ok": True, "filename": output_path.name}


@app.get("/health-professional/{token}/annotate/{conversation_id}")
def health_professional_annotate(
    token: str,
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    submission = get_or_create_submission(db, current_user.id, conversation)
    annotations = db.scalars(
        select(Annotation)
        .where(Annotation.submission_id == submission.id)
        .order_by(Annotation.created_at.asc())
    ).all()

    return template_response(
        "health_professional_annotate.html",
        {
            "request": request,
            "current_user": current_user,
            "conversation": conversation,
            "submission": submission,
            "annotations": annotations,
            "access_token": token,
            "health_professional_base_path": f"/health-professional/{token}",
        },
    )


@app.post("/health-professional/{token}/submission/{conversation_id}/save-draft")
def save_draft(
    token: str,
    conversation_id: str,
    payload: SaveDraftRequest,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    submission = get_or_create_submission(db, current_user.id, conversation)
    if submission.status == "submitted":
        return JSONResponse({"ok": False, "error": "Submission already submitted."}, status_code=400)

    submission.translated_text_edited = payload.translated_text_edited
    submission.status = "draft"
    submission.last_saved_at = datetime.utcnow()
    db.commit()

    return {
        "ok": True,
        "status": submission.status,
        "last_saved_at": submission.last_saved_at.strftime("%H:%M:%S"),
    }


@app.post("/health-professional/{token}/submission/{conversation_id}/submit")
def submit_submission(
    token: str,
    conversation_id: str,
    payload: SubmitRequest,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    submission = get_or_create_submission(db, current_user.id, conversation)
    if not payload.consent_confirmed:
        return JSONResponse({"ok": False, "error": "Consent is required before submit."}, status_code=400)
    if not submission.translated_text_edited.strip():
        return JSONResponse({"ok": False, "error": "Edited Chinese text cannot be empty."}, status_code=400)

    submission.status = "submitted"
    submission.consent_confirmed = True
    submission.last_saved_at = datetime.utcnow()
    submission.submitted_at = datetime.utcnow()
    db.commit()

    return {
        "ok": True,
        "status": submission.status,
        "submitted_at": submission.submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.post("/health-professional/{token}/submission/{conversation_id}/discard")
def discard_draft(
    token: str,
    conversation_id: str,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    submission = get_or_create_submission(db, current_user.id, conversation)
    if submission.status == "submitted":
        return JSONResponse({"ok": False, "error": "Cannot discard after submission."}, status_code=400)

    db.query(Annotation).filter(Annotation.submission_id == submission.id).delete()
    submission.translated_text_edited = conversation.chinese_text
    submission.status = "draft"
    submission.consent_confirmed = False
    submission.submitted_at = None
    submission.last_saved_at = datetime.utcnow()
    db.commit()

    return {
        "ok": True,
        "status": submission.status,
        "translated_text_edited": submission.translated_text_edited,
        "last_saved_at": submission.last_saved_at.strftime("%H:%M:%S"),
    }


@app.get("/health-professional/{token}/submission/{conversation_id}/annotations")
def list_annotations(
    token: str,
    conversation_id: str,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    submission = get_or_create_submission(db, current_user.id, conversation)
    annotations = db.scalars(
        select(Annotation)
        .where(Annotation.submission_id == submission.id)
        .order_by(Annotation.created_at.asc())
    ).all()

    return {
        "ok": True,
        "annotations": [
            {
                "id": a.id,
                "start_char": a.start_char,
                "end_char": a.end_char,
                "error_type": a.error_type,
                "severity": a.severity,
                "clinical_significance": a.clinical_significance,
                "subtlety": a.subtlety,
                "inserted_error_text": a.inserted_error_text,
                "original_text": a.original_text,
                "note": a.note,
                "created_at": a.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for a in annotations
        ],
    }


@app.post("/health-professional/{token}/submission/{conversation_id}/annotations")
def add_annotation(
    token: str,
    conversation_id: str,
    payload: AnnotationCreateRequest,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    submission = get_or_create_submission(db, current_user.id, conversation)
    if submission.status == "submitted":
        return JSONResponse({"ok": False, "error": "Cannot edit annotations after submission."}, status_code=400)

    edited_text = submission.translated_text_edited or ""
    text_len = len(edited_text)
    if not (0 <= payload.start_char < payload.end_char <= text_len):
        return JSONResponse({"ok": False, "error": "Invalid selection span."}, status_code=400)
    if not (1 <= payload.clinical_significance <= 5):
        return JSONResponse({"ok": False, "error": "Clinical significance must be 1 to 5."}, status_code=400)
    if not (1 <= payload.subtlety <= 5):
        return JSONResponse({"ok": False, "error": "Subtlety must be 1 to 5."}, status_code=400)
    inserted_error_text = edited_text[payload.start_char : payload.end_char]
    original_base = conversation.chinese_text or ""
    original_text = original_base[payload.start_char : min(payload.end_char, len(original_base))]

    annotation = Annotation(
        submission_id=submission.id,
        start_char=payload.start_char,
        end_char=payload.end_char,
        error_type=payload.error_type or "Inserted Error",
        severity=f"CS:{payload.clinical_significance}|Subtlety:{payload.subtlety}",
        clinical_significance=payload.clinical_significance,
        subtlety=payload.subtlety,
        inserted_error_text=inserted_error_text,
        original_text=original_text,
        note=payload.note.strip(),
    )
    db.add(annotation)
    submission.last_saved_at = datetime.utcnow()
    db.commit()
    db.refresh(annotation)

    return {
        "ok": True,
        "annotation": {
            "id": annotation.id,
            "start_char": annotation.start_char,
            "end_char": annotation.end_char,
            "error_type": annotation.error_type,
            "severity": annotation.severity,
            "clinical_significance": annotation.clinical_significance,
            "subtlety": annotation.subtlety,
            "inserted_error_text": annotation.inserted_error_text,
            "original_text": annotation.original_text,
            "note": annotation.note,
            "created_at": annotation.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


@app.post("/health-professional/{token}/submission/{conversation_id}/annotations/{annotation_id}/delete")
def delete_annotation(
    token: str,
    conversation_id: str,
    annotation_id: int,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "health_professional")
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    submission = get_or_create_submission(db, current_user.id, conversation)
    if submission.status == "submitted":
        return JSONResponse({"ok": False, "error": "Cannot edit annotations after submission."}, status_code=400)

    annotation = db.scalar(
        select(Annotation).where(
            Annotation.id == annotation_id,
            Annotation.submission_id == submission.id,
        )
    )
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    db.delete(annotation)
    submission.last_saved_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.get("/admin/{token}/upload")
def admin_upload_page(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": None,
            "error": None,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.post("/admin/{token}/create-health-professional")
def admin_create_health_professional(
    token: str,
    request: Request,
    health_professional_name: str = Form(...),
    health_professional_role: str = Form(...),
    health_professional_email: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)

    name = normalize_name(health_professional_name)
    professional_role = normalize_professional_role(health_professional_role)
    email = normalize_email(health_professional_email)
    if not name:
        return template_response(
            "admin_upload.html",
            {
                "request": request,
                "current_user": current_user,
                "message": None,
                "error": "Please enter a health professional name.",
                "metadata_rows": metadata_rows,
                "health_professional_progress_rows": health_professional_progress_rows,
                "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
                "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
                "access_token": token,
            },
            status_code=400,
        )
    if not professional_role:
        return template_response(
            "admin_upload.html",
            {
                "request": request,
                "current_user": current_user,
                "message": None,
                "error": "Please enter a professional role (for example: nurse, doctor, pharmacist).",
                "metadata_rows": metadata_rows,
                "health_professional_progress_rows": health_professional_progress_rows,
                "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
                "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
                "access_token": token,
            },
            status_code=400,
        )
    if not email or "@" not in email:
        return template_response(
            "admin_upload.html",
            {
                "request": request,
                "current_user": current_user,
                "message": None,
                "error": "Please enter a valid health professional email.",
                "metadata_rows": metadata_rows,
                "health_professional_progress_rows": health_professional_progress_rows,
                "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
                "access_token": token,
            },
            status_code=400,
        )

    user = db.scalar(select(User).where(User.email == email))
    if user:
        user.name = name
        user.professional_role = professional_role
        user.role = "health_professional"
        if not user.access_token:
            user.access_token = secrets.token_urlsafe(16)
    else:
        user = User(
            name=name,
            professional_role=professional_role,
            email=email,
            password_hash=hash_password("link-only-auth-disabled"),
            role="health_professional",
            access_token=secrets.token_urlsafe(16),
        )
        db.add(user)
    db.commit()

    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    link = f"http://127.0.0.1:8000/health-professional/{user.access_token}/tasks"
    message = f"Health professional link ready: {name} ({professional_role}, {email}) -> {link}"
    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": message,
            "error": None,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.post("/admin/{token}/delete-health-professional")
def admin_delete_health_professional(
    token: str,
    request: Request,
    health_professional_email: str = Form(...),
    db: Session = Depends(get_db),
):
    _ = require_user_by_token(db, token, "admin")

    email = normalize_email(health_professional_email)
    target = db.scalar(
        select(User).where(User.email == email, User.role == "health_professional")
    )
    if not target:
        # Avoid warning loops on browser refresh after a previous successful deletion.
        return redirect(f"/admin/{token}/upload")

    deleted = delete_health_professional_related_data(db, target)
    _ = deleted
    return redirect(f"/admin/{token}/upload")


@app.get("/admin/{token}/workspace-screenshot")
def admin_download_workspace_screenshot(
    token: str,
    health_professional_email: str = Query(...),
    dataset_name: str = Query(...),
    db: Session = Depends(get_db),
):
    _ = require_user_by_token(db, token, "admin")
    normalized_email = (health_professional_email or "").strip().lower()
    health_professional = db.scalar(select(User).where(User.email == normalized_email, User.role == "health_professional"))
    if not health_professional:
        raise HTTPException(status_code=404, detail="Health Professional not found")

    screenshot_path = get_workspace_screenshot_path(health_professional.id, dataset_name)
    if not screenshot_path.exists():
        raise HTTPException(status_code=404, detail="Workspace screenshot not found")

    safe_email = slugify_filename_part(normalized_email)
    safe_dataset = slugify_filename_part(dataset_name)
    filename = f"workspace_screenshot_{safe_email}_{safe_dataset}.png"
    return FileResponse(str(screenshot_path), media_type="image/png", filename=filename)


@app.post("/admin/{token}/upload")
async def admin_upload_submit(
    token: str,
    request: Request,
    dataset_name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return template_response(
            "admin_upload.html",
            {
                "request": request,
                "current_user": current_user,
                "message": None,
                "error": "Could not decode file. Please upload UTF-8 CSV.",
                "metadata_rows": metadata_rows,
                "health_professional_progress_rows": health_professional_progress_rows,
                "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
                "access_token": token,
            },
            status_code=400,
        )

    reader = csv.DictReader(io.StringIO(text))
    required_columns = {"conversation_id", "turn_id", "speaker", "english_text", "chinese_text"}
    if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
        return template_response(
            "admin_upload.html",
            {
                "request": request,
                "current_user": current_user,
                "message": None,
                "error": "CSV must contain columns: conversation_id, turn_id, speaker, english_text, chinese_text",
                "metadata_rows": metadata_rows,
                "health_professional_progress_rows": health_professional_progress_rows,
                "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
                "access_token": token,
            },
            status_code=400,
        )

    normalized_dataset_name = (dataset_name or "").strip()
    if not normalized_dataset_name:
        return template_response(
            "admin_upload.html",
            {
                "request": request,
                "current_user": current_user,
                "message": None,
                "error": "Dataset name is required.",
                "metadata_rows": metadata_rows,
                "health_professional_progress_rows": health_professional_progress_rows,
                "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
                "access_token": token,
            },
            status_code=400,
        )
    if "/" in normalized_dataset_name or "\\" in normalized_dataset_name:
        return template_response(
            "admin_upload.html",
            {
                "request": request,
                "current_user": current_user,
                "message": None,
                "error": "Dataset name cannot contain / or \\ characters.",
                "metadata_rows": metadata_rows,
                "health_professional_progress_rows": health_professional_progress_rows,
                "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
                "access_token": token,
            },
            status_code=400,
        )

    rows = list(reader)
    uploaded_filename = (file.filename or '').strip()
    inserted, updated = upsert_conversations_from_rows(db, rows, normalized_dataset_name, uploaded_filename)
    message = (
        f"Upload complete for dataset '{normalized_dataset_name}'. "
        f"Inserted: {inserted}, Updated: {updated}."
    )
    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)

    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": message,
            "error": None,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.post("/admin/{token}/delete-dataset")
def admin_delete_dataset(
    token: str,
    request: Request,
    dataset_name: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    target_dataset = (dataset_name or "").strip()
    counts = delete_dataset_by_name(db, target_dataset)
    message = (
        f"Deleted dataset '{target_dataset}'. "
        f"Conversations: {counts['conversations_deleted']}, "
        f"Submissions: {counts['submissions_deleted']}, "
        f"Annotations: {counts['annotations_deleted']}."
    )

    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": message,
            "error": None,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.post("/admin/{token}/assign-health-professional-datasets")
def admin_assign_health_professional_datasets(
    token: str,
    request: Request,
    health_professional_email: str = Form(...),
    dataset_name_1: str = Form(...),
    dataset_name_2: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    email = normalize_email(health_professional_email)
    dataset_1 = (dataset_name_1 or "").strip()
    dataset_2 = (dataset_name_2 or "").strip()
    available = set(get_available_dataset_names(db))

    if not dataset_1 or not dataset_2:
        message = None
        error = "Please select two datasets."
    elif dataset_1 == dataset_2:
        message = None
        error = "Please select two different datasets."
    elif dataset_1 not in available or dataset_2 not in available:
        message = None
        error = "One or both selected datasets are not available."
    else:
        user = db.scalar(select(User).where(User.email == email, User.role == "health_professional"))
        if not user:
            message = None
            error = "Health professional not found."
        else:
            db.query(HealthProfessionalDatasetAssignment).filter(
                HealthProfessionalDatasetAssignment.health_professional_id == user.id
            ).delete(synchronize_session=False)
            db.add(
                HealthProfessionalDatasetAssignment(
                    health_professional_id=user.id, slot=1, dataset_name=dataset_1
                )
            )
            db.add(
                HealthProfessionalDatasetAssignment(
                    health_professional_id=user.id, slot=2, dataset_name=dataset_2
                )
            )
            db.commit()
            message = f"Assigned datasets to {email}: {dataset_1}, {dataset_2}"
            error = None

    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": message,
            "error": error,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.post("/admin/{token}/clear")
def admin_clear_uploaded_data(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    counts = clear_uploaded_conversations(db)
    message = (
        "Cleanup complete. "
        f"Deleted conversations: {counts['conversations_deleted']}, "
        f"submissions: {counts['submissions_deleted']}, "
        f"annotations: {counts['annotations_deleted']}."
    )
    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": message,
            "error": None,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.post("/admin/{token}/clear-submitted")
def admin_clear_submitted_output(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    counts = clear_submitted_output(db)
    message = (
        "Submitted output cleanup complete. "
        f"Deleted submitted submissions: {counts['submissions_deleted']}, "
        f"annotations: {counts['annotations_deleted']}."
    )
    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": message,
            "error": None,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.post("/admin/{token}/clear-health-professional-tasks")
def admin_clear_health_professional_tasks(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user_by_token(db, token, "admin")
    counts = clear_all_health_professional_tasks(db)
    message = (
        "Health Professional task cleanup complete. "
        f"Deleted submissions: {counts['submissions_deleted']}, "
        f"annotations: {counts['annotations_deleted']}. "
        "Uploaded conversations were kept."
    )
    metadata_rows = get_admin_metadata_rows(db)
    health_professional_progress_rows = get_health_professional_progress_rows(db)
    health_professional_dataset_export_rows = get_health_professional_dataset_export_rows(db)
    return template_response(
        "admin_upload.html",
        {
            "request": request,
            "current_user": current_user,
            "message": message,
            "error": None,
            "metadata_rows": metadata_rows,
            "health_professional_progress_rows": health_professional_progress_rows,
            "health_professional_dataset_export_rows": health_professional_dataset_export_rows,
            "health_professional_link_rows": get_health_professional_link_rows(db),
            "uploaded_dataset_rows": get_uploaded_dataset_rows(db),
            "available_dataset_names": get_available_dataset_names(db),
            "access_token": token,
        },
    )


@app.get("/admin/{token}/export")
def admin_export_csv(
    token: str,
    db: Session = Depends(get_db),
):
    _ = require_user_by_token(db, token, "admin")
    rows = get_submitted_export_rows(db)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "dataset_name",
            "conversation_id",
            "turn_id",
            "speaker",
            "health_professional_email",
            "english_text",
            "chinese_text",
            "translated_text_edited",
            "turn_modified",
            "submitted_at",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    output.seek(0)
    filename = f"submitted_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


@app.get("/admin/{token}/export/health-professional/{health_professional_email}")
def admin_export_csv_by_health_professional(
    token: str,
    health_professional_email: str,
    db: Session = Depends(get_db),
):
    _ = require_user_by_token(db, token, "admin")
    rows = get_submitted_export_rows(db, health_professional_email=health_professional_email)

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "dataset_name",
            "conversation_id",
            "turn_id",
            "speaker",
            "health_professional_email",
            "english_text",
            "chinese_text",
            "translated_text_edited",
            "turn_modified",
            "submitted_at",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    safe_email = "".join(ch if ch.isalnum() or ch in {"@", ".", "_", "-"} else "_" for ch in health_professional_email)
    output.seek(0)
    filename = f"submitted_export_{safe_email}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


@app.get("/admin/{token}/export/health-professional/{health_professional_email}/dataset/{dataset_name}")
def admin_export_csv_by_health_professional_dataset(
    token: str,
    health_professional_email: str,
    dataset_name: str,
    db: Session = Depends(get_db),
):
    _ = require_user_by_token(db, token, "admin")
    rows = [
        row for row in get_submitted_export_rows(db, health_professional_email=health_professional_email)
        if (row.get("dataset_name") or "") == dataset_name
    ]

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "dataset_name",
            "conversation_id",
            "turn_id",
            "speaker",
            "health_professional_email",
            "english_text",
            "chinese_text",
            "translated_text_edited",
            "turn_modified",
            "submitted_at",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    safe_email = "".join(ch if ch.isalnum() or ch in {"@", ".", "_", "-"} else "_" for ch in health_professional_email)
    safe_dataset = "".join(ch if ch.isalnum() or ch in {"@", ".", "_", "-"} else "_" for ch in dataset_name)
    output.seek(0)
    filename = f"submitted_export_{safe_email}_{safe_dataset}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)


@app.get("/admin/{token}/export-by-health-professional-dataset")
def admin_export_csv_by_health_professional_dataset_query(
    token: str,
    health_professional_email: str = Query(...),
    dataset_name: str = Query(...),
    db: Session = Depends(get_db),
):
    _ = require_user_by_token(db, token, "admin")
    rows = [
        row for row in get_submitted_export_rows(db, health_professional_email=health_professional_email)
        if (row.get("dataset_name") or "") == dataset_name
    ]

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "dataset_name",
            "conversation_id",
            "turn_id",
            "speaker",
            "health_professional_email",
            "english_text",
            "chinese_text",
            "translated_text_edited",
            "turn_modified",
            "submitted_at",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

    safe_email = "".join(ch if ch.isalnum() or ch in {"@", ".", "_", "-"} else "_" for ch in health_professional_email)
    safe_dataset = "".join(ch if ch.isalnum() or ch in {"@", ".", "_", "-"} else "_" for ch in dataset_name)
    output.seek(0)
    filename = f"submitted_export_{safe_email}_{safe_dataset}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers=headers)

