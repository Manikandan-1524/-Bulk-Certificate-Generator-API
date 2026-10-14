# Bulk Certificate Generator API

A lightweight FastAPI application for generating PDF completion certificates in bulk. It accepts recipient data, creates a background job, tracks per-recipient status, exposes the results through a JSON API, and serves a browser UI plus downloadable certificate PDFs and ZIP archives.

## Features

- Create certificate jobs using a course name, issue date, and recipient list.
- Parse recipients in the documented `name, email` format.
- Validate recipient names and email addresses individually.
- Process certificates asynchronously so valid recipients complete without blocking the request.
- Track job status and per-recipient success or failure.
- Return paginated certificate records through an HTTP API.
- Download individual successful certificate PDFs.
- Download all successful certificates from a job as a ZIP archive.
- Serve a built-in browser interface at `/ui`.
- Generate a certificate preview in the browser from the current form values.
- Preserve user input and report backend/database errors without leaking internal stack traces.

## Technology stack

- Python
- FastAPI
- Uvicorn
- SQLAlchemy
- SQLite
- ReportLab
- pytest
- httpx

## Project structure

```text
Bulk-Certificate-Generator-API/
├── app/
│   ├── main.py
│   ├── api/
│   ├── core/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   └── static/
│       └── index.html
├── tests/
├── .gitignore
├── README.md
└── requirements.txt
```

## Prerequisites

- Python 3.10 or later
- pip
- No separate database server is required; SQLite creates `certificates.db` locally when the application runs.

## Installation

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Running the application

```powershell
$env:PYTHONUTF8 = "1"
python -m uvicorn app.main:app --reload
```

The application is usually available at:

- Health check: `http://127.0.0.1:8000/health`
- API documentation: `http://127.0.0.1:8000/docs`
- Browser UI: `http://127.0.0.1:8000/ui`

## Running the tests

```powershell
$env:PYTHONUTF8 = "1"
python -m pytest -v
```

## Main API endpoints

- `GET /health`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/certificates`
- `GET /jobs/{job_id}/certificates/{certificate_id}/download`
- `GET /jobs/{job_id}/download`

`POST /jobs` accepts JSON such as:

```json
{
  "course_name": "Python Basics",
  "issue_date": "2026-10-13",
  "recipients": [
    { "name": "Anna", "email": "anna@example.com" },
    { "name": "Ravi", "email": "ravi@example.com" }
  ]
}
```

Jobs may have the statuses `pending`, `processing`, `completed`, `completed_with_errors`, and `failed`. Each recipient certificate can have the statuses `pending`, `success`, or `failed`.

## Important limitations

- The certificate template supports Latin characters and the accents available in the certificate font's code page.
- Tamil, Chinese, emoji, and other unsupported scripts or symbols are rejected during certificate generation rather than rendered incorrectly.
- Certificate PDFs are placed under the local `generated_certificates/` directory during development and are excluded from this repository.
- The default SQLite database is created locally and is also excluded from version control.