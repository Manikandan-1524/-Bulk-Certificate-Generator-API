import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_recipient(recipient: dict) -> tuple:
    name_raw = recipient.get("name", None) if isinstance(recipient, dict) else None
    email_raw = recipient.get("email", None) if isinstance(recipient, dict) else None

    name_error = None
    email_error = None

    if not isinstance(name_raw, str):
        name_error = "Invalid name: must be a non-empty string up to 100 characters"
    else:
        name_stripped = name_raw.strip()
        if name_stripped == "" or len(name_stripped) > 100:
            name_error = "Invalid name: must be a non-empty string up to 100 characters"

    if not isinstance(email_raw, str):
        email_error = "Invalid email: must be a valid email address"
    else:
        email_stripped = email_raw.strip()
        if len(email_stripped) > 254 or not EMAIL_RE.match(email_stripped):
            email_error = "Invalid email: must be a valid email address"

    errors = []
    if name_error:
        errors.append(name_error)
    if email_error:
        errors.append(email_error)
    error_message = "; ".join(errors) if errors else None

    name = name_raw.strip() if isinstance(name_raw, str) else None
    email = email_raw.strip() if isinstance(email_raw, str) else None
    return name, email, error_message