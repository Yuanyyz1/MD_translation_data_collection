# Data Columns Guide

## Uploaded CSV: Required Columns

The admin upload CSV must include these columns exactly:

| Column | Required | Description |
|---|---|---|
| `conversation_id` | Yes | Conversation/group identifier. Multiple rows can share the same value. |
| `turn_id` | Yes | Turn identifier within a conversation. |
| `speaker` | Yes | Speaker label for the turn, for example `Health Professional` or `Patient`. |
| `english_text` | Yes | English source text for the turn. |
| `chinese_text` | Yes | Chinese translated text for the turn. |

## Exported CSV: Columns

The submitted export CSV includes these columns:

| Column | Description |
|---|---|
| `dataset_name` | Dataset name entered during upload. |
| `conversation_id` | Conversation/group identifier. |
| `turn_id` | Turn identifier within the conversation. |
| `speaker` | Speaker label for the turn. |
| `health_professional_email` | Health Professional account email for the submitted row. |
| `english_text` | English source text. |
| `chinese_text` | Chinese translated text. |
| `translated_text_edited` | Final submitted text from `Translated conversations with errors`. |
| `turn_modified` | `yes` if the submitted edited text differs from the baseline text for that turn, otherwise `no`. |
| `submitted_at` | Submission timestamp in ISO format. |

## Notes

- Upload file format must be `.csv`.
- Upload encoding should be `UTF-8` or `UTF-8 with BOM`.
- Only rows with submission status `submitted` are included in exported CSV files.
