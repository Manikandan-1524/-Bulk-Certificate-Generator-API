import os

import pytest

from app.models.certificate import Certificate
from app.models.job import Job
from app.services.validation import validate_recipient

from tests.helpers import (
    ANNA,
    NAME_ERROR,
    EMAIL_ERROR,
    make_payload,
    submit,
    get_certificate_list,
)


VALID_RECIPIENT = {"name": "Anna", "email": "anna@example.com"}


def _payload(**changes):
    data = {
        "course_name": "Python Basics",
        "issue_date": "2026-10-13",
        "recipients": [VALID_RECIPIENT],
    }
    data.update(changes)
    return data


def _without(key):
    data = _payload()
    del data[key]
    return data


INVALID_PAYLOADS = [
    pytest.param(_without("course_name"), id="missing-course-name"),
    pytest.param(_payload(course_name=""), id="empty-course-name"),
    pytest.param(_payload(course_name="   "), id="whitespace-course-name"),
    pytest.param(_payload(course_name="A" * 201), id="course-name-too-long"),
    pytest.param(_payload(course_name=123), id="course-name-number"),
    pytest.param(_without("issue_date"), id="missing-issue-date"),
    pytest.param(_payload(issue_date="13-2026"), id="issue-date-bad-format"),
    pytest.param(_payload(issue_date="2026-13-45"), id="issue-date-impossible"),
    pytest.param(_payload(issue_date=""), id="issue-date-empty"),
    pytest.param(_without("recipients"), id="missing-recipients"),
    pytest.param(_payload(recipients=[]), id="recipients-empty-list"),
    pytest.param(_payload(recipients="abc"), id="recipients-string"),
    pytest.param(_payload(recipients=None), id="recipients-null"),
    pytest.param(_payload(recipients=["abc"]), id="recipients-list-of-string"),
    pytest.param(_payload(recipients=[123]), id="recipients-list-of-number"),
    pytest.param(_payload(recipients=[None]), id="recipients-list-of-null"),
    pytest.param({}, id="empty-body"),
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_invalid_request_is_rejected_with_422(client, session_factory, certs_dir, payload):
    response = client.post("/jobs", json=payload)
    assert response.status_code == 422

    db = session_factory()
    try:
        assert db.query(Job).count() == 0
        assert db.query(Certificate).count() == 0
    finally:
        db.close()

    assert os.listdir(certs_dir) == []


def test_course_name_rules_are_applied(client, session_factory):
    response = client.post("/jobs", json=_payload(course_name="A" * 200))
    assert response.status_code == 202

    data = submit(client, [ANNA], course_name="  Python Basics  ")
    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == data["job_id"]).first()
        assert job is not None
        assert job.course_name == "Python Basics"
    finally:
        db.close()


VALID_RECIPIENT_CASES = [
    ({"name": "Anna", "email": "anna@example.com"}, ("Anna", "anna@example.com", None)),
    ({"name": "  Anna  ", "email": "  anna@example.com  "}, ("Anna", "anna@example.com", None)),
    ({"name": "A" * 100, "email": "a@b.co"}, ("A" * 100, "a@b.co", None)),
    ({"name": "Anna", "email": "a" * 248 + "@x.com"}, ("Anna", "a" * 248 + "@x.com", None)),
    ({"name": "Anna", "email": "anna@example.com", "extra": "ignored"}, ("Anna", "anna@example.com", None)),
]


@pytest.mark.parametrize("recipient,expected", VALID_RECIPIENT_CASES)
def test_valid_recipients_pass(recipient, expected):
    assert validate_recipient(recipient) == expected


INVALID_NAME_CASES = [
    {},
    {"name": None},
    {"name": ""},
    {"name": "   "},
    {"name": 123},
    {"name": "A" * 101},
    {"name": ["Anna"]},
]


@pytest.mark.parametrize("recipient", INVALID_NAME_CASES)
def test_invalid_names_are_rejected(recipient):
    recipient = dict(recipient)
    recipient["email"] = "anna@example.com"
    result = validate_recipient(recipient)
    assert result[2] == NAME_ERROR


INVALID_EMAIL_CASES = [
    {},
    {"email": None},
    {"email": ""},
    {"email": "abc"},
    {"email": "a@b"},
    {"email": "a b@x.com"},
    {"email": "@x.com"},
    {"email": "anna@@example.com"},
    {"email": 123},
    {"email": "a" * 250 + "@x.com"},
]


@pytest.mark.parametrize("recipient", INVALID_EMAIL_CASES)
def test_invalid_emails_are_rejected(recipient):
    recipient = dict(recipient)
    recipient["name"] = "Anna"
    result = validate_recipient(recipient)
    assert result[2] == EMAIL_ERROR


def test_both_invalid_returns_both_messages():
    result = validate_recipient({"name": "", "email": "abc"})
    assert "Invalid name" in (result[2] or "")
    assert "Invalid email" in (result[2] or "")
    assert "; " in (result[2] or "")


def test_invalid_recipient_is_saved_as_failed_with_error_message(client):
    data = submit(client, [ANNA, {"name": "", "email": "bad.name@example.com"}])
    items = get_certificate_list(client, data["job_id"])["certificates"]
    assert len(items) == 2

    anna_item = next(item for item in items if item["recipient_name"] == "Anna")
    bad_item = next(item for item in items if item["recipient_name"] == "")

    assert anna_item["status"] == "success"
    assert bad_item["status"] == "failed"
    assert bad_item["error_message"] == NAME_ERROR
    assert bad_item["download_url"] is None


def test_recipient_values_are_trimmed_when_saved(client):
    data = submit(client, [{"name": "  Anna  ", "email": " anna@example.com "}])
    items = get_certificate_list(client, data["job_id"])["certificates"]
    assert len(items) == 1
    assert items[0]["recipient_name"] == "Anna"
    assert items[0]["recipient_email"] == "anna@example.com"