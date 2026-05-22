# Bilingual Doctor Annotation Prototype

Beginner-friendly prototype for collecting doctor annotations on translated medical conversations.

## Features
- Admin upload of conversation CSV (`conversation_id,turn_id,speaker,english_text,chinese_text`)
- Doctor workflow to edit Chinese translation and insert errors
- Autosave draft (debounced on edit, periodic autosave, blur save, and page-exit save)
- Submit with required consent checkbox
- Admin export of submitted-only records to CSV
- Link-based access (no email/password login)

## Project Structure
```text
backend/    FastAPI app + SQLAlchemy models/auth/routes
templates/  Jinja2 HTML pages
static/     CSS + vanilla JavaScript
scripts/    seed/import/export helper scripts
```

## Prerequisites
- Python 3.10+

## How To Run
1. Create virtual environment:
   ```powershell
   python -m venv .venv
   ```
2. (Optional) Activate it (PowerShell):
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1

   ```
3. Install dependencies:
   ```powershell
   .\.venv\Scripts\python -m pip install -r requirements.txt
   ```
4. Seed users:
   ```powershell
   .\.venv\Scripts\python scripts/seed.py
   ```
5. Start the app:
   ```powershell
   .\.venv\Scripts\python -m uvicorn backend.main:app --reload
   ```
6. Open in browser:
   - `http://127.0.0.1:8000/`
7. Verify installed packages in the venv (optional):
   ```powershell
   .\.venv\Scripts\python -m pip list
   ```

## Uploaded CSV Requirements
- Each upload must include a dataset name (you set this in Admin upload form).
- File type: `.csv`
- Encoding: `UTF-8` (UTF-8 with BOM is also accepted)
- Header row is required.
- Required columns (exact names):
  - `conversation_id`
  - `turn_id`
  - `speaker`
  - `english_text`
  - `chinese_text`
- Multiple rows can share the same `conversation_id` (same conversation across turns).
- `turn_id` should be unique within each `conversation_id`.
- Empty `conversation_id` rows are ignored.
- Example header:
  - `conversation_id,turn_id,speaker,english_text,chinese_text`
- Example row:
  - `conv_001,12,Doctor,How are you feeling today?,你今天感觉怎么样？`

## UI Label To Field Mapping
- The labels shown in the doctor workspace are UI text only. The underlying code/database fields are:
  - `Original conversations` -> `english_text`
  - `Translated conversations` -> `chinese_text`
  - `Translated conversations with errors` -> usually `translated_text_edited`
- Current workspace note:
  - For patient rows, the first two visible columns are swapped in the UI.
  - For patient rows, the left column shows plain `chinese_text`.
  - For patient rows, `Translated conversations` shows highlighted `english_text`.
  - For patient rows, `Translated conversations with errors` uses saved `translated_text_edited` when available, otherwise it falls back to `english_text`.
  - For non-patient rows, `Translated conversations` shows highlighted `chinese_text`.
  - For non-patient rows, `Translated conversations with errors` uses saved `translated_text_edited` when available, otherwise it falls back to `chinese_text`.
- Prompting tip:
  - If you want a UI text change only, refer to the visible label.
  - If you want a data or logic change, refer to the field name such as `english_text`, `chinese_text`, or `translated_text_edited`.

## PowerShell Note (Windows)
- If activation is blocked with `running scripts is disabled`, either:
  - use temporary bypass in current terminal:
    ```powershell
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\.venv\Scripts\Activate.ps1
    ```
  - or skip activation and always run explicit `.\.venv\Scripts\python ...` commands.

## Access Method
- This app now uses direct access links instead of login/password.
- After running `python scripts/seed.py`, terminal output includes:
  - admin link
  - default doctor link
- `ACCESS_LINKS.md` is auto-updated when you run:
  - `python scripts/seed.py`
  - `python scripts/create_doctor.py ...`
- `http://127.0.0.1:8000/` no longer shows tokens for safety.
- Admin links only work for admin routes.
- Doctor links only work for doctor routes.
- Each doctor should have a unique link/token.
- Current local links (updated on March 6, 2026):
  - Admin upload: `http://127.0.0.1:8000/admin/qzBUat4nehtQo1cUw84dOQ/upload`
  - Doctor tasks: `http://127.0.0.1:8000/doctor/mq_Ca6spWMAXM41uezIf7w/tasks`
  - Doctor error insertion page (conversation `5_12`): `http://127.0.0.1:8000/doctor/mq_Ca6spWMAXM41uezIf7w/annotate/5_12`
  - If you reseed users or recreate DB data, these tokenized links may change.

## Create Different Doctor Links
- Create one or multiple doctor users (each gets a different link):
  ```powershell
  .\.venv\Scripts\python scripts/create_doctor.py doc1@example.com doc2@example.com
  ```
- Script output prints each doctor's private access link.
- Share each doctor only their own link.

## How To Use
1. Open the admin access link.
2. Enter a dataset name and upload a CSV with headers:
   - `conversation_id,turn_id,speaker,english_text,chinese_text`
3. (Optional) Click `Clear Uploaded Data` in admin page to remove all currently uploaded conversations and related submissions/annotations.
4. (Optional) Click `Clear Submitted Output` in admin page to remove only submitted outputs and related annotations (uploaded conversations are kept).
5. (Optional) Click `Clear All Doctor Tasks` in admin page to remove all doctor submissions (draft + submitted) and annotations while keeping uploaded conversations.
6. Open a doctor-specific access link.
7. Select which uploaded dataset (CSV file) to work on.
8. Review all turns in one page (ordered by `turn_id`) with three columns: `Original conversations`, `Translated conversations`, `Translated conversations with errors`.
9. Edit text in the right-side `Translated conversations with errors` box for each turn.
10. Drafts save automatically while editing, when a field loses focus, and when leaving the page; the page uses one `Submit All Conversations` button to upload all turns on the page.
11. After a successful `Submit All Conversations`, the doctor workspace also saves a screenshot of the page for admin review.
12. Return to admin link and export submitted-only CSV or download the saved workspace screenshot for that doctor and dataset.

## How To Test (Manual)
1. Open admin link and upload a valid CSV.
2. Open doctor link and open a task.
3. Edit text and confirm drafts are saved without submitting, including after blur or leaving and reopening the task page.
4. Attempt submit without consent; verify it is blocked.
5. Submit with consent; verify submitted status appears.
6. Admin export should include submitted rows only, with a `turn_modified` column showing whether the exported `translated_text_edited` differs from that turn's baseline text.
7. Create a draft-only task and verify it is excluded from export.
8. Use `Discard Draft` on a draft task; verify edited text resets to baseline.
9. After a successful full submission, confirm the admin page can download the saved workspace screenshot for that doctor and dataset.

## CLI Helpers
- Refresh `ACCESS_LINKS.md` manually:
  ```powershell
  .\.venv\Scripts\python scripts/sync_access_links_md.py
  ```
- List doctor email-to-link mapping:
  ```powershell
  .\.venv\Scripts\python scripts/list_doctor_links.py
  ```
- Import CSV via script:
  ```powershell
  .\.venv\Scripts\python scripts/import_csv.py your_dataset_name path\to\your.csv
  ```
- Export submitted CSV via script:
  ```powershell
  .\.venv\Scripts\python scripts/export_csv.py output.csv
  ```

## Remove Doctors Or Links
- Remove a doctor account (and their submissions/annotations) by email:
  ```powershell
  .\.venv\Scripts\python -c "from backend.database import SessionLocal; from backend.models import User, Submission, Annotation; from sqlalchemy import select; email='doctor@example.com'; db=SessionLocal(); u=db.scalar(select(User).where(User.email==email, User.role=='doctor')); import sys; 
  if not u: print('Doctor not found'); db.close(); sys.exit(0)
  subs=db.scalars(select(Submission).where(Submission.doctor_id==u.id)).all()
  sub_ids=[s.id for s in subs]
  if sub_ids: db.query(Annotation).filter(Annotation.submission_id.in_(sub_ids)).delete(synchronize_session=False)
  db.query(Submission).filter(Submission.doctor_id==u.id).delete(synchronize_session=False)
  db.delete(u); db.commit(); db.close(); print(f'Removed doctor: {email}')"
  ```
- Invalidate/rotate a doctor link only (keep the doctor account):
  ```powershell
  .\.venv\Scripts\python -c "import secrets; from backend.database import SessionLocal; from backend.models import User; from sqlalchemy import select; email='doctor@example.com'; db=SessionLocal(); u=db.scalar(select(User).where(User.email==email, User.role=='doctor')); import sys; 
  if not u: print('Doctor not found'); db.close(); sys.exit(0)
  u.access_token=secrets.token_urlsafe(16); db.commit(); print(f'New link: http://127.0.0.1:8000/doctor/{u.access_token}/tasks'); db.close()"
  ```
- After either action, refresh the markdown registry:
  ```powershell
  .\.venv\Scripts\python scripts/sync_access_links_md.py
  ```

## Regenerate Access Links
- To regenerate links for users that do not have one, run:
  ```powershell
  .\.venv\Scripts\python scripts/seed.py
  ```

## GitHub Update Workflow (Beginner Friendly)
- Use this every time you want to upload your latest code changes:
  1. Check what changed:
     ```powershell
     git status
     ```
  2. Stage all changes:
     ```powershell
     git add .
     ```
  3. Save a checkpoint with a short message:
     ```powershell
     git commit -m "Describe what you changed"
     ```
  4. Upload to GitHub:
     ```powershell
     git push
     ```

## GitHub Update Using VS Code Buttons
- You can use VS Code Source Control instead of terminal commands:
  1. Open **Source Control** (branch icon in the left sidebar).
  2. Review changed files.
  3. Type a commit message (for example: `update error instructions`).
  4. Click **Commit**.
  5. Click **Sync Changes** (or **Push**) to upload to GitHub.
- Important:
  - **Commit** saves changes locally on your computer.
  - **Push/Sync Changes** uploads those committed changes to GitHub.

## About `.gitignore` in This Project
- `.gitignore` is a "do not upload" list for Git.
- This project now ignores:
  - virtual environments like `.venv/`
  - Python cache files like `__pycache__/`
  - local database files like `*.db`
  - local screenshots in `workspace_screenshots/`
  - `ACCESS_LINKS.md` (contains tokenized private links)
- If any of these files were already tracked before adding `.gitignore`, untrack them once:
  ```powershell
  git rm --cached ACCESS_LINKS.md
  git rm -r --cached .venv workspace_screenshots
  git rm --cached *.db *.db-journal *.db-wal *.db-shm
  git commit -m "Stop tracking local files via .gitignore"
  git push
  ```

## Data File
- SQLite database file: `app.db` (created in project root)

## Troubleshooting
- `ModuleNotFoundError: No module named 'sqlalchemy'`
  - Install dependencies with the venv interpreter:
    ```powershell
    .\.venv\Scripts\python -m pip install -r requirements.txt
    ```
- `ModuleNotFoundError: No module named 'itsdangerous'`
  - Reinstall dependencies from `requirements.txt` to ensure all packages are present:
    ```powershell
    .\.venv\Scripts\python -m pip install -r requirements.txt
    ```
- passlib/bcrypt compatibility errors
  - This project pins compatible versions in `requirements.txt`:
    - `passlib[bcrypt]==1.7.4`
    - `bcrypt==4.0.1`
  - Reinstall requirements if needed:
    ```powershell
    .\.venv\Scripts\python -m pip install --force-reinstall -r requirements.txt
    ```
