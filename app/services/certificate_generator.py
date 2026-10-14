import os
import unicodedata

from datetime import date
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


def _wrap_text(text: str, font_name: str, font_size: int, max_width: float) -> list[str]:
    words = [w for w in text.split(" ") if w != ""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if current == "" else current + " " + word
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue

        if current != "":
            lines.append(current)
            current = ""

        if stringWidth(word, font_name, font_size) <= max_width:
            current = word
            continue

        # Split the over-wide word by characters
        chunk = ""
        for ch in word:
            if chunk == "" or stringWidth(chunk + ch, font_name, font_size) <= max_width:
                chunk += ch
            else:
                if chunk != "":
                    lines.append(chunk)
                chunk = ch
        current = chunk

    if current != "":
        lines.append(current)

    return lines


def _normalize_supported(label: str, text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise ValueError(
            f"{label} contains characters that the certificate font cannot display (only Latin letters are supported)"
        ) from None
    return text


def generate_certificate_pdf(recipient_name: str, course_name: str, issue_date: date, output_path: str) -> None:
    recipient_name = _normalize_supported("Recipient name", recipient_name)
    course_name = _normalize_supported("Course name", course_name)

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    c = canvas.Canvas(output_path, pagesize=landscape(A4))
    width, height = landscape(A4)

    c.rect(20, 20, width - 40, height - 40)
    c.rect(30, 30, width - 60, height - 60)

    c.setFont("Helvetica-Bold", 40)
    c.drawCentredString(width / 2, 470, "Certificate of Completion")

    c.setFont("Helvetica", 18)
    c.drawCentredString(width / 2, 410, "This is to certify that")

    size = 36
    while size > 6 and stringWidth(recipient_name, "Helvetica-Bold", size) > 680:
        size -= 1
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(width / 2, 360, recipient_name)

    c.setFont("Helvetica", 18)
    c.drawCentredString(width / 2, 310, "has successfully completed")

    lines = []
    chosen_size = 12
    for size in range(22, 11, -1):
        lines = _wrap_text(course_name, "Helvetica-Bold", size, 680)
        if len(lines) <= 4:
            chosen_size = size
            break
    else:
        chosen_size = 12
        lines = _wrap_text(course_name, "Helvetica-Bold", chosen_size, 680)

    if len(lines) > 4:
        lines = lines[:4]

    c.setFont("Helvetica-Bold", chosen_size)
    y = 270
    for line in lines:
        c.drawCentredString(width / 2, y, line)
        y -= chosen_size + 6

    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, 110, "Date of issue: " + issue_date.strftime("%d %B %Y"))

    c.save()