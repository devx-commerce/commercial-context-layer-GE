from app.normalization import email_document, slack_document


def test_email_document_id_is_deterministic_from_message_id():
    id_a = email_document.compute_document_id("<abc123@mail.gmail.com>", "a@x.com", "b@y.com", "date", "subj", "body")
    id_b = email_document.compute_document_id("abc123@mail.gmail.com", "different", "recipients", "other", "s", "b")
    assert id_a == id_b  # Message-ID alone determines identity when present


def test_email_document_id_falls_back_to_content_hash_when_no_message_id():
    id_a = email_document.compute_document_id(None, "a@x.com", "b@y.com", "2026-01-01", "subj", "body")
    id_b = email_document.compute_document_id(None, "a@x.com", "b@y.com", "2026-01-01", "subj", "body")
    id_c = email_document.compute_document_id(None, "a@x.com", "b@y.com", "2026-01-01", "subj", "different body")
    assert id_a == id_b
    assert id_a != id_c


def test_email_document_build_contains_expected_fields():
    doc = email_document.build(
        message_id="<abc@x.com>",
        sender="a@x.com",
        to="b@y.com",
        cc="",
        subject="Q3 campaign scope",
        sent_at="2026-08-25T10:30:00Z",
        body_mime_type="text/plain",
        body_text="Hello there",
    )
    assert doc.title == "Email: Q3 campaign scope"
    assert "Hello there" in doc.html
    assert "<h1>Email: Q3 campaign scope</h1>" in doc.html


def test_slack_document_id_is_stable_per_workspace_channel_ts():
    id_a = slack_document.compute_document_id("T1", "C1", "1234.5678")
    id_b = slack_document.compute_document_id("T1", "C1", "1234.5678")
    id_c = slack_document.compute_document_id("T1", "C1", "9999.0000")
    assert id_a == id_b
    assert id_a != id_c


def test_slack_document_build_title_includes_channel_and_timestamp():
    doc = slack_document.build(
        workspace_id="T1",
        channel_id="C1",
        channel_name="ext-hindustan-times",
        message_ts="1234.5678",
        author_name="Person Name",
        sent_at="2026-08-25T10:35:00Z",
        thread_ts=None,
        resolved_text="hello <script>alert(1)</script>",
    )
    assert "ext-hindustan-times" in doc.title
    assert "2026-08-25T10:35:00Z" in doc.title
    assert "&lt;script&gt;" in doc.html  # escaped, not executable
