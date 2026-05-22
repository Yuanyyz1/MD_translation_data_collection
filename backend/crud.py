from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Annotation, Conversation, Submission, User


def get_or_create_submission(db: Session, doctor_id: int, conversation: Conversation) -> Submission:
    submission = db.scalar(
        select(Submission).where(
            Submission.doctor_id == doctor_id,
            Submission.conversation_id == conversation.id,
        )
    )
    if submission:
        return submission

    submission = Submission(
        doctor_id=doctor_id,
        conversation_id=conversation.id,
        translated_text_edited=conversation.chinese_text,
        status="draft",
        consent_confirmed=False,
        last_saved_at=datetime.utcnow(),
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def upsert_conversations_from_rows(db: Session, rows: list[dict[str, str]], dataset_name: str) -> tuple[int, int]:
    inserted = 0
    updated = 0

    # Normalize by (conversation_id, turn_id) so one conversation can contain
    # multiple turns while still de-duplicating repeated rows for the same turn.
    normalized_rows: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        conversation_id = str(row.get("conversation_id", "")).strip()
        turn_id = str(row.get("turn_id", "")).strip()
        if not conversation_id:
            continue
        normalized_rows[(conversation_id, turn_id)] = row

    for (conversation_id, turn_id), row in normalized_rows.items():
        turn_id = str(row.get("turn_id", "")).strip()
        speaker = str(row.get("speaker", "")).strip()
        english_text = str(row.get("english_text", "")).strip()
        chinese_text = str(row.get("chinese_text", "")).strip()
        internal_id = f"{dataset_name}__conv__{conversation_id}__turn__{turn_id or '0'}"

        conversation = db.get(Conversation, internal_id)
        if conversation:
            conversation.dataset_name = dataset_name
            conversation.conversation_group_id = conversation_id
            conversation.turn_id = turn_id
            conversation.speaker = speaker
            conversation.english_text = english_text
            conversation.chinese_text = chinese_text
            updated += 1
        else:
            db.add(
                Conversation(
                    id=internal_id,
                    dataset_name=dataset_name,
                    conversation_group_id=conversation_id,
                    turn_id=turn_id,
                    speaker=speaker,
                    english_text=english_text,
                    chinese_text=chinese_text,
                )
            )
            inserted += 1

    db.commit()
    return inserted, updated


def clear_uploaded_conversations(db: Session) -> dict[str, int]:
    annotation_count = db.query(Annotation).delete()
    submission_count = db.query(Submission).delete()
    conversation_count = db.query(Conversation).delete()
    db.commit()
    return {
        "annotations_deleted": int(annotation_count or 0),
        "submissions_deleted": int(submission_count or 0),
        "conversations_deleted": int(conversation_count or 0),
    }


def clear_submitted_output(db: Session) -> dict[str, int]:
    submitted_submission_ids = db.scalars(
        select(Submission.id).where(Submission.status == "submitted")
    ).all()
    if not submitted_submission_ids:
        return {
            "annotations_deleted": 0,
            "submissions_deleted": 0,
        }

    annotation_count = db.query(Annotation).filter(Annotation.submission_id.in_(submitted_submission_ids)).delete(
        synchronize_session=False
    )
    submission_count = db.query(Submission).filter(Submission.id.in_(submitted_submission_ids)).delete(
        synchronize_session=False
    )
    db.commit()
    return {
        "annotations_deleted": int(annotation_count or 0),
        "submissions_deleted": int(submission_count or 0),
    }


def clear_all_doctor_tasks(db: Session) -> dict[str, int]:
    submission_ids = db.scalars(select(Submission.id)).all()
    if not submission_ids:
        return {
            "annotations_deleted": 0,
            "submissions_deleted": 0,
        }

    annotation_count = db.query(Annotation).filter(Annotation.submission_id.in_(submission_ids)).delete(
        synchronize_session=False
    )
    submission_count = db.query(Submission).delete(synchronize_session=False)
    db.commit()
    return {
        "annotations_deleted": int(annotation_count or 0),
        "submissions_deleted": int(submission_count or 0),
    }


def get_submitted_export_rows(db: Session, doctor_email: str | None = None) -> list[dict[str, str]]:
    query = (
        select(Submission)
        .where(Submission.status == "submitted")
        .order_by(Submission.submitted_at.desc())
    )
    submissions = db.scalars(query).all()
    if doctor_email:
        normalized_email = doctor_email.strip().lower()
        submissions = [s for s in submissions if (s.doctor.email or "").strip().lower() == normalized_email]

    rows: list[dict[str, str]] = []
    for submission in submissions:
        baseline_text = submission.conversation.english_text if (
            (submission.conversation.speaker or "").strip().lower() in {"patient"}
        ) else submission.conversation.chinese_text
        has_inserted_errors = "yes" if (submission.translated_text_edited or "") != (baseline_text or "") else "no"
        rows.append(
            {
                "dataset_name": submission.conversation.dataset_name,
                "conversation_id": submission.conversation.conversation_group_id or submission.conversation_id,
                "turn_id": submission.conversation.turn_id,
                "speaker": submission.conversation.speaker,
                "doctor_email": submission.doctor.email,
                "english_text": submission.conversation.english_text,
                "chinese_text": submission.conversation.chinese_text,
                "translated_text_edited": submission.translated_text_edited,
                "turn_modified": has_inserted_errors,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
            }
        )
    return rows


def get_admin_metadata_rows(db: Session) -> list[dict[str, str]]:
    submissions = db.scalars(
        select(Submission)
        .where(Submission.status == "submitted")
        .order_by(Submission.submitted_at.desc())
    ).all()

    rows: list[dict[str, str]] = []
    for submission in submissions:
        rows.append(
            {
                "dataset_name": submission.conversation.dataset_name,
                "conversation_id": submission.conversation.conversation_group_id or submission.conversation_id,
                "doctor_email": submission.doctor.email,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
                "edited_text_length": str(len(submission.translated_text_edited or "")),
            }
        )
    return rows


def get_doctor_progress_rows(db: Session) -> list[dict[str, str]]:
    conversations = db.scalars(select(Conversation)).all()
    doctors = db.scalars(select(User).where(User.role == "doctor").order_by(User.email.asc())).all()
    dataset_to_conversation_ids: dict[str, set[str]] = {}
    for conversation in conversations:
        dataset_name = (conversation.dataset_name or "default").strip() or "default"
        dataset_to_conversation_ids.setdefault(dataset_name, set()).add(conversation.id)

    rows: list[dict[str, str]] = []
    for doctor in doctors:
        submissions = db.scalars(select(Submission).where(Submission.doctor_id == doctor.id)).all()
        submitted_conversation_ids = {s.conversation_id for s in submissions if s.status == "submitted"}
        submitted_count = sum(
            1 for conversation_ids in dataset_to_conversation_ids.values()
            if conversation_ids and conversation_ids.issubset(submitted_conversation_ids)
        )
        draft_count = len([s for s in submissions if s.status == "draft"])
        started_count = len(submissions)
        total_conversations = len(conversations)
        not_started_count = max(total_conversations - started_count, 0)
        total_datasets = len(dataset_to_conversation_ids)
        completion_rate = (submitted_count / total_datasets * 100.0) if total_datasets > 0 else 0.0

        rows.append(
            {
                "doctor_email": doctor.email,
                "total_conversations": str(total_conversations),
                "submitted_count": str(submitted_count),
                "draft_count": str(draft_count),
                "not_started_count": str(not_started_count),
                "completion_rate": f"{completion_rate:.1f}%",
            }
        )
    return rows


def get_doctor_dataset_export_rows(db: Session) -> list[dict[str, str]]:
    submissions = db.scalars(
        select(Submission)
        .where(Submission.status == "submitted")
        .order_by(Submission.submitted_at.desc())
    ).all()

    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for submission in submissions:
        doctor_email = submission.doctor.email
        dataset_name = submission.conversation.dataset_name
        key = (doctor_email, dataset_name)
        baseline_text = submission.conversation.english_text if (
            (submission.conversation.speaker or "").strip().lower() in {"patient"}
        ) else submission.conversation.chinese_text
        is_modified = (submission.translated_text_edited or "") != (baseline_text or "")
        if key not in grouped:
            grouped[key] = {
                "doctor_email": doctor_email,
                "dataset_name": dataset_name,
                "submitted_count": "0",
                "modified_count": "0",
                "last_submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
            }
        grouped[key]["submitted_count"] = str(int(grouped[key]["submitted_count"]) + 1)
        if is_modified:
            grouped[key]["modified_count"] = str(int(grouped[key]["modified_count"]) + 1)
        submitted_at = submission.submitted_at.isoformat() if submission.submitted_at else ""
        if submitted_at and submitted_at > grouped[key]["last_submitted_at"]:
            grouped[key]["last_submitted_at"] = submitted_at

    rows = list(grouped.values())
    rows.sort(key=lambda row: ((row["doctor_email"] or "").lower(), (row["dataset_name"] or "").lower()))
    return rows
