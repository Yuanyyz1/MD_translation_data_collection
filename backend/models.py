from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    professional_role: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False, default="")
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # admin or health_professional

    submissions: Mapped[list["Submission"]] = relationship("Submission", back_populates="health_professional")
    dataset_assignments: Mapped[list["HealthProfessionalDatasetAssignment"]] = relationship(
        "HealthProfessionalDatasetAssignment",
        back_populates="health_professional",
        cascade="all, delete-orphan",
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    conversation_group_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    turn_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    speaker: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    english_text: Mapped[str] = mapped_column(Text, nullable=False)
    chinese_text: Mapped[str] = mapped_column(Text, nullable=False)
    duplicated_from_id: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    created_by_health_professional_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    submissions: Mapped[list["Submission"]] = relationship("Submission", back_populates="conversation")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("health_professional_id", "conversation_id", name="uq_submission_health_professional_conversation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(100), ForeignKey("conversations.id"), nullable=False, index=True)
    health_professional_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    translated_text_edited: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    health_professional: Mapped[User] = relationship("User", back_populates="submissions")
    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="submissions")
    annotations: Mapped[list["Annotation"]] = relationship(
        "Annotation", back_populates="submission", cascade="all, delete-orphan"
    )


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    clinical_significance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subtlety: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inserted_error_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    original_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    submission: Mapped[Submission] = relationship("Submission", back_populates="annotations")


class HealthProfessionalDatasetAssignment(Base):
    __tablename__ = "health_professional_dataset_assignments"
    __table_args__ = (
        UniqueConstraint("health_professional_id", "slot", name="uq_hp_dataset_assignment_slot"),
        UniqueConstraint("health_professional_id", "dataset_name", name="uq_hp_dataset_assignment_dataset"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    health_professional_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 or 2
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False)

    health_professional: Mapped[User] = relationship("User", back_populates="dataset_assignments")


class WorkspaceScreenshot(Base):
    __tablename__ = "workspace_screenshots"
    __table_args__ = (
        UniqueConstraint(
            "health_professional_id",
            "dataset_name",
            name="uq_workspace_screenshot_hp_dataset",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    health_professional_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    image_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
