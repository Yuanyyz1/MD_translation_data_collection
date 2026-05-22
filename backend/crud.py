from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Annotation,
    Conversation,
    HealthProfessionalDatasetAssignment,
    Submission,
    User,
)


def get_or_create_submission(db: Session, health_professional_id: int, conversation: Conversation) -> Submission:
    submission = db.scalar(
        select(Submission).where(
            Submission.health_professional_id == health_professional_id,
            Submission.conversation_id == conversation.id,
        )
    )
    if submission:
        return submission

    submission = Submission(
        health_professional_id=health_professional_id,
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


def upsert_conversations_from_rows(
    db: Session,
    rows: list[dict[str, str]],
    dataset_name: str,
    source_filename: str = "",
) -> tuple[int, int]:
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
            conversation.source_filename = source_filename or conversation.source_filename
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
                    source_filename=source_filename,
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


def clear_all_health_professional_tasks(db: Session) -> dict[str, int]:
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


def get_submitted_export_rows(db: Session, health_professional_email: str | None = None) -> list[dict[str, str]]:
    query = (
        select(Submission)
        .where(Submission.status == "submitted")
        .order_by(Submission.submitted_at.desc())
    )
    submissions = db.scalars(query).all()
    if health_professional_email:
        normalized_email = health_professional_email.strip().lower()
        submissions = [s for s in submissions if (s.health_professional.email or "").strip().lower() == normalized_email]

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
                "health_professional_email": submission.health_professional.email,
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
                "health_professional_email": submission.health_professional.email,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
                "edited_text_length": str(len(submission.translated_text_edited or "")),
            }
        )
    return rows


def get_health_professional_progress_rows(db: Session) -> list[dict[str, str]]:
    conversations = db.scalars(select(Conversation)).all()
    health_professionals = db.scalars(select(User).where(User.role == "health_professional").order_by(User.email.asc())).all()
    dataset_to_conversation_ids: dict[str, set[str]] = {}
    for conversation in conversations:
        dataset_name = (conversation.dataset_name or "default").strip() or "default"
        dataset_to_conversation_ids.setdefault(dataset_name, set()).add(conversation.id)

    rows: list[dict[str, str]] = []
    for health_professional in health_professionals:
        submissions = db.scalars(select(Submission).where(Submission.health_professional_id == health_professional.id)).all()
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
                "health_professional_email": health_professional.email,
                "total_conversations": str(total_conversations),
                "submitted_count": str(submitted_count),
                "draft_count": str(draft_count),
                "not_started_count": str(not_started_count),
                "completion_rate": f"{completion_rate:.1f}%",
            }
        )
    return rows


def get_health_professional_dataset_export_rows(db: Session) -> list[dict[str, str]]:
    submissions = db.scalars(
        select(Submission)
        .where(Submission.status == "submitted")
        .order_by(Submission.submitted_at.desc())
    ).all()

    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for submission in submissions:
        health_professional_email = submission.health_professional.email
        dataset_name = submission.conversation.dataset_name
        key = (health_professional_email, dataset_name)
        baseline_text = submission.conversation.english_text if (
            (submission.conversation.speaker or "").strip().lower() in {"patient"}
        ) else submission.conversation.chinese_text
        is_modified = (submission.translated_text_edited or "") != (baseline_text or "")
        if key not in grouped:
            grouped[key] = {
                "health_professional_email": health_professional_email,
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
    rows.sort(key=lambda row: ((row["health_professional_email"] or "").lower(), (row["dataset_name"] or "").lower()))
    return rows


def get_uploaded_dataset_rows(db: Session) -> list[dict[str, str]]:
    conversations = db.scalars(select(Conversation)).all()
    assignments = db.scalars(select(HealthProfessionalDatasetAssignment)).all()
    user_by_id = {
        user.id: user
        for user in db.scalars(select(User).where(User.role == "health_professional")).all()
    }
    grouped: dict[str, dict[str, str]] = {}
    for conversation in conversations:
        dataset_name = (conversation.dataset_name or "default").strip() or "default"
        source_filename = (conversation.source_filename or "").strip()
        row = grouped.setdefault(
            dataset_name,
            {
                "dataset_name": dataset_name,
                "source_filename": source_filename,
                "turn_count": "0",
            },
        )
        row["turn_count"] = str(int(row["turn_count"]) + 1)
        if source_filename and not row["source_filename"]:
            row["source_filename"] = source_filename

    assigned_by_dataset: dict[str, list[str]] = {}
    for assignment in assignments:
        dataset_name = (assignment.dataset_name or "").strip()
        if not dataset_name:
            continue
        user = user_by_id.get(assignment.health_professional_id)
        if not user:
            continue
        label_name = (user.name or "").strip()
        label = f"{label_name} ({user.email})" if label_name else user.email
        assigned_by_dataset.setdefault(dataset_name, [])
        if label not in assigned_by_dataset[dataset_name]:
            assigned_by_dataset[dataset_name].append(label)

    for dataset_name, row in grouped.items():
        assignees = assigned_by_dataset.get(dataset_name, [])
        assignees.sort(key=str.lower)
        row["assigned_to"] = ", ".join(assignees)

    rows = list(grouped.values())
    rows.sort(key=lambda row: (row["dataset_name"] or "").lower())
    return rows


def delete_dataset_by_name(db: Session, dataset_name: str) -> dict[str, int]:
    normalized = (dataset_name or "").strip()
    if not normalized:
        return {
            "conversations_deleted": 0,
            "submissions_deleted": 0,
            "annotations_deleted": 0,
        }

    conversation_ids = db.scalars(
        select(Conversation.id).where(Conversation.dataset_name == normalized)
    ).all()
    if not conversation_ids:
        return {
            "conversations_deleted": 0,
            "submissions_deleted": 0,
            "annotations_deleted": 0,
        }

    submission_ids = db.scalars(
        select(Submission.id).where(Submission.conversation_id.in_(conversation_ids))
    ).all()

    annotations_deleted = 0
    if submission_ids:
        annotations_deleted = db.query(Annotation).filter(
            Annotation.submission_id.in_(submission_ids)
        ).delete(synchronize_session=False)

    submissions_deleted = db.query(Submission).filter(
        Submission.conversation_id.in_(conversation_ids)
    ).delete(synchronize_session=False)

    conversations_deleted = db.query(Conversation).filter(
        Conversation.id.in_(conversation_ids)
    ).delete(synchronize_session=False)

    db.commit()
    return {
        "conversations_deleted": int(conversations_deleted or 0),
        "submissions_deleted": int(submissions_deleted or 0),
        "annotations_deleted": int(annotations_deleted or 0),
    }
