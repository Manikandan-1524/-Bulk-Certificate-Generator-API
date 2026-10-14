import os

import pytest
from datetime import date
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.models.certificate import Certificate
from app.services import certificate_generator
from app.services.certificate_generator import generate_certificate_pdf, _wrap_text

from tests.helpers import MIXED_RECIPIENTS, submit

REAL_CANVAS = canvas.Canvas


def test_generate_pdf_creates_a_valid_pdf_file(tmp_path):
    output_path = tmp_path / "nested" / "cert.pdf"
    generate_certificate_pdf("Anna", "Python Basics", date(2026, 10, 13), str(output_path))

    assert output_path.exists()
    assert output_path.stat().st_size > 0
    assert output_path.read_bytes().startswith(b"%PDF")


def test_pdf_contains_recipient_information(tmp_path, monkeypatch):
    drawn = []

    class RecordingCanvas(REAL_CANVAS):
        def drawCentredString(self, x, y, text, *args, **kwargs):
            drawn.append(text)
            return super().drawCentredString(x, y, text, *args, **kwargs)

    if hasattr(certificate_generator, "canvas"):
        monkeypatch.setattr(certificate_generator.canvas, "Canvas", RecordingCanvas)
    else:
        monkeypatch.setattr(certificate_generator, "Canvas", RecordingCanvas)

    output_path = tmp_path / "c.pdf"
    generate_certificate_pdf("Anna", "Python Basics", date(2026, 10, 13), str(output_path))

    assert "Certificate of Completion" in drawn
    assert "Anna" in drawn
    assert "Python Basics" in drawn
    assert any("13 October 2026" in text for text in drawn)
    assert output_path.exists()
    assert output_path.read_bytes().startswith(b"%PDF")


def test_generate_pdf_handles_longest_allowed_values(tmp_path):
    name = "W" * 100
    course = "W" * 200
    output_path = tmp_path / "long.pdf"
    generate_certificate_pdf(name, course, date(2026, 10, 13), str(output_path))

    assert output_path.exists()
    assert output_path.read_bytes().startswith(b"%PDF")


def test_generation_errors_are_not_hidden(tmp_path):
    blocker = tmp_path / "blocker.txt"
    blocker.write_text("blocker")
    output_path = str(blocker / "x.pdf")

    with pytest.raises(OSError):
        generate_certificate_pdf("Anna", "Python Basics", date(2026, 10, 13), output_path)


def test_wrap_text_keeps_short_text_on_one_line():
    assert _wrap_text("Python Basics", "Helvetica-Bold", 22, 680) == ["Python Basics"]


def test_wrap_text_splits_very_long_words():
    lines = _wrap_text("W" * 200, "Helvetica-Bold", 22, 680)
    assert len(lines) > 1
    assert all(stringWidth(line, "Helvetica-Bold", 22) <= 680 for line in lines)
    assert "".join(lines) == "W" * 200


def test_job_creates_one_pdf_per_valid_recipient(client, session_factory, certs_dir):
    data = submit(client, MIXED_RECIPIENTS)
    job_id = data["job_id"]

    db = session_factory()
    try:
        certs = db.query(Certificate).filter(Certificate.job_id == job_id).all()
    finally:
        db.close()

    success_certs = [c for c in certs if c.status == "success"]
    failed_certs = [c for c in certs if c.status == "failed"]

    assert len(success_certs) == 2
    for certificate in success_certs:
        expected_path = os.path.join(certs_dir, job_id, f"{certificate.id}.pdf")
        assert certificate.file_path == expected_path
        assert os.path.isfile(certificate.file_path)
        with open(certificate.file_path, "rb") as f:
            assert f.read(4) == b"%PDF"

    folder = os.path.join(certs_dir, job_id)
    assert len(os.listdir(folder)) == 2

    assert all(c.file_path is None for c in failed_certs)


def test_special_characters_in_name_do_not_affect_file_path(client, session_factory, certs_dir):
    recipients = [{"name": "O'Brien / Test", "email": "ob@example.com"}]
    data = submit(client, recipients)
    job_id = data["job_id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    db = session_factory()
    try:
        cert = db.query(Certificate).filter(Certificate.job_id == job_id).first()
    finally:
        db.close()

    assert cert is not None
    assert os.path.dirname(cert.file_path) == os.path.join(certs_dir, job_id)
    assert os.path.isfile(cert.file_path)