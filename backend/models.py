from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False, default="")
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # admin or doctor

    submissions: Mapped[list["Submission"]] = relationship("Submission", back_populates="doctor")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    conversation_group_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    turn_id: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    speaker: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    english_text: Mapped[str] = mapped_column(Text, nullable=False)
    chinese_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    submissions: Mapped[list["Submission"]] = relationship("Submission", back_populates="conversation")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("doctor_id", "conversation_id", name="uq_submission_doctor_conversation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(100), ForeignKey("conversations.id"), nullable=False, index=True)
    doctor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    translated_text_edited: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    doctor: Mapped[User] = relationship("User", back_populates="submissions")
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
