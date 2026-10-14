from pathlib import Path

INDEX_FILE = Path(__file__).resolve().parent.parent / "app" / "static" / "index.html"

EXPECTED_PATHS = {
    "/health",
    "/jobs",
    "/jobs/{job_id}",
    "/jobs/{job_id}/certificates",
    "/jobs/{job_id}/certificates/{certificate_id}/download",
    "/jobs/{job_id}/download",
}


def test_ui_page_is_served(client):
    response = client.get("/ui")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Bulk Certificate Generator" in response.text
    assert 'id="submitBtn"' in response.text


def test_root_redirects_to_ui(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/ui"


def test_ui_routes_are_hidden_from_api_docs(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert set(response.json()["paths"].keys()) == EXPECTED_PATHS


def test_ui_page_is_safe_and_works_offline():
    text = INDEX_FILE.read_text(encoding="utf-8")
    assert "innerHTML" not in text
    assert "http://" not in text
    assert "https://" not in text
def test_ui_page_has_no_text_after_closing_html_tag():
    text = INDEX_FILE.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    assert text.rstrip().endswith("</html>")
    assert text.count("</html>") == 1
    for marker in ("<" + "|", "```" * 3):
        assert marker not in text

def test_ui_page_has_every_element_the_script_needs():
    text = INDEX_FILE.read_text(encoding="utf-8")
    ids = [
        "courseName", "issueDate", "recipients", "recCount", "submitBtn",
        "createMsg", "jobIdInput", "openBtn", "openMsg", "jobCard", "jobId",
        "jobInfo", "jobStatus", "percent", "ringFill", "sTotal", "sSuccess",
        "sFailed", "sPending", "zipLink", "statusFilter", "certBody",
        "pageInfo", "prevBtn", "nextBtn", "pvName", "pvCourse", "pvDate",
        "seal",
    ]
    for element_id in ids:
        assert text.count('id="' + element_id + '"') == 1, element_id
    assert text.count("<script>") == 1
    assert text.count("</script>") == 1
    assert "xmlns" not in text


def test_ui_page_uses_premium_design_tokens():
    text = INDEX_FILE.read_text(encoding="utf-8")
    assert "--navy:#142536" in text
    assert "--gold:#c6a15b" in text
    assert "--ivory:#f7f5f0" in text
    assert "@media (max-width:1080px)" in text
    assert "Create certificates" in text
