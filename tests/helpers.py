from app.services import certificate_generator

ANNA = {"name": "Anna", "email": "anna@example.com"}
RAVI = {"name": "Ravi", "email": "ravi@example.com"}
ZOE = {"name": "Zoe", "email": "zoe@example.com"}
FAIL_ME = {"name": "Fail Me", "email": "failme@example.com"}

GOOD_RECIPIENTS = [ANNA, RAVI]

# 2 good recipients and 3 bad ones
MIXED_RECIPIENTS = [
    ANNA,
    RAVI,
    {"name": "", "email": "empty.name@example.com"},
    {"name": "Bad Email", "email": "abc"},
    {"name": 123, "email": "number.name@example.com"},
]

NAME_ERROR = "Invalid name: must be a non-empty string up to 100 characters"
EMAIL_ERROR = "Invalid email: must be a valid email address"


def make_payload(recipients, course_name="Python Basics", issue_date="2026-10-13"):
    return {
        "course_name": course_name,
        "issue_date": issue_date,
        "recipients": recipients,
    }


def make_recipients(count):
    return [
        {"name": f"Person {i}", "email": f"person{i}@example.com"}
        for i in range(count)
    ]


def make_invalid_recipients(count):
    return [{"name": "", "email": "abc"} for _ in range(count)]


def submit(client, recipients, **payload_options):
    response = client.post("/jobs", json=make_payload(recipients, **payload_options))
    assert response.status_code == 202, response.text
    return response.json()


def get_certificate_list(client, job_id, query=""):
    response = client.get(f"/jobs/{job_id}/certificates{query}")
    assert response.status_code == 200, response.text
    return response.json()


def install_flaky_generator(monkeypatch, failing_names):
    real_function = certificate_generator.generate_certificate_pdf

    def flaky(recipient_name, course_name, issue_date, output_path):
        if recipient_name in failing_names:
            raise RuntimeError("forced failure")
        return real_function(recipient_name, course_name, issue_date, output_path)

    monkeypatch.setattr("app.services.job_processor.generate_certificate_pdf", flaky)