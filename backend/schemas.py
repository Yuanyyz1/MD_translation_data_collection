from pydantic import BaseModel, Field


class SaveDraftRequest(BaseModel):
    translated_text_edited: str = Field(default="")


class SubmitRequest(BaseModel):
    consent_confirmed: bool


class AnnotationCreateRequest(BaseModel):
    start_char: int
    end_char: int
    error_type: str = Field(default="Inserted Error")
    clinical_significance: int
    subtlety: int
    note: str = ""


class WorkspaceScreenshotUploadRequest(BaseModel):
    dataset_name: str
    image_base64: str
