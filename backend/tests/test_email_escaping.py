"""Text a stranger types into a public form must reach an inbox as text.

The registration form and the contact form accept any name, company, location
and subject, from anyone, for any email address. Before this was fixed, a name
containing a link went out as a live link inside a genuine ProReadyEngineer
email, to whatever address the sender chose.
"""
from __future__ import annotations

from types import SimpleNamespace

from app import emailer
from app import support_service as svc

LINK = '<a href="https://evil.example/pay">Pay for your seat here</a>'


def _no_live_markup(html: str) -> None:
    assert "evil.example/pay\">" not in html
    assert "<a href=\"https://evil.example" not in html
    assert "&lt;a href=" in html  # shown as the text that was typed


def test_registration_confirmation_shows_a_typed_link_as_text():
    html = emailer.applicant_confirmation_html(
        full_name=f"Al {LINK}", course_title="Gas Turbine Emissions Mapping",
        cohort="November 14, 2026", price_display="", payment_instructions="We will email you.",
    )
    _no_live_markup(html)
    assert "Thanks, Al " in html


def test_new_registration_alert_shows_typed_values_as_text():
    html = emailer.admin_notification_html(
        reg={"Name": f"Al {LINK}", "Company": LINK, "Location": "Kitimat, BC"},
        taken_after=3, capacity=15,
    )
    _no_live_markup(html)
    assert "Kitimat, BC" in html


def test_session_reminder_escapes_the_name_and_the_registrants_location():
    html = emailer.session_reminder_html(
        full_name=f"{LINK} Smith", course_title="Gas Turbine Emissions Mapping",
        day=1, total_days=4,
        when_lines=["14:00 UTC on Saturday, November 14",
                    f"07:00 PT in Kitimat {LINK} — your local time"],
        meeting_info="Join: https://meet.google.com/abc-defg-hij", lead_minutes=60,
    )
    _no_live_markup(html)
    # the real joining link is still a link
    assert 'href="https://meet.google.com/abc-defg-hij"' in html
    assert "14:00 UTC on Saturday, November 14" in html


def test_ordinary_names_read_exactly_as_typed():
    html = emailer.applicant_confirmation_html(
        full_name="Seán O'Brien & Sons", course_title="Gas Turbine Emissions Mapping",
        cohort="November 14, 2026", price_display="", payment_instructions="x",
    )
    # entities, which every mail client renders back to the characters typed
    assert "Thanks, Seán O&#x27;Brien &amp; Sons." in html
    assert emailer.login_link_html("Fatima Al-Zahra", "https://x.example/l", 30).count("Hi Fatima Al-Zahra,") == 1


def test_candidate_note_to_the_instructor_is_text():
    html = emailer.advanced_slots_admin_html(
        learner_name=f"Eve {LINK}", learner_email="eve@example.com",
        course_title="Micro Gas Turbine Design", slots_lines=["Mon 09:00"],
        note=LINK, admin_url="https://proreadyengineer.com/admin#certification",
    )
    _no_live_markup(html)


def test_support_acknowledgement_escapes_subject_and_name(monkeypatch):
    sent = {}
    monkeypatch.setattr(svc, "send_ticket_email",
                        lambda db, ticket, body_html: (sent.setdefault("html", body_html), (True, "id"))[1])
    monkeypatch.setattr(svc, "add_message", lambda *a, **k: None)
    monkeypatch.setattr(svc, "emit_event", lambda *a, **k: None)
    ticket = SimpleNamespace(submitter_name=f"{LINK} X", subject=f"Refund {LINK}", first_responded_at=None)
    svc._send_acknowledgement(None, ticket)
    _no_live_markup(sent["html"])
    assert "Refund &lt;a href=" in sent["html"]


def test_integrity_alert_shows_the_reported_page_address_as_text():
    html = emailer.integrity_alert_html(
        "A copy called home", "meaning",
        [("Opened at", f"file:///C:/x {LINK}"), ("Time zone", "<b>Europe/Paris</b>")],
        next_steps="", integrity_url="https://proreadyengineer.com/admin#academy",
    )
    _no_live_markup(html)
    assert "&lt;b&gt;Europe/Paris&lt;/b&gt;" in html
