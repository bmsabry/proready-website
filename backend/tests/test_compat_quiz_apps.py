"""Contract tests for the legacy quiz-app compatibility layer.

These five apps are already deployed and cannot be re-tested by hand, so the
contract they expect is pinned here: exact endpoint paths, exact response
fields, and the entitlement rule that replaced the old per-module grants.

The headline behaviour under test: one academy purchase opens all five apps.
"""
from __future__ import annotations

import pytest

import conftest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Learner  # noqa: E402
from app.routes.compat import MODULES, decode_token, hash_password  # noqa: E402

PRODUCT = "micro-gas-turbine-design"
ADMIN = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
BUYER = "buyer@example.com"
STRANGER = "stranger@example.com"
PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def c():
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def set_password_then_login(c, email: str, password: str) -> str:
    """Walk the real onboarding path for someone who already has access.

    Admin mints a sign-in link -> the learner opens it, which proves the
    mailbox -> they set a password from that session -> the quiz apps take it.
    """
    link = c.post(
        "/api/admin/academy/login-link", headers=ADMIN, json={"email": email}
    ).json()["link"]
    session = TestClient(app, base_url="https://testserver")
    assert session.post(
        "/api/academy/auth/verify", json={"token": link.split("token=")[1]}
    ).status_code == 200
    assert session.post(
        "/api/academy/auth/set-password", json={"password": password}
    ).status_code == 200
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# -----------------------------------------------------------------------------
# Signup / login
# -----------------------------------------------------------------------------

def test_signup_returns_the_legacy_token_shape(c):
    r = c.post("/auth/signup", json={
        "email": STRANGER, "password": PASSWORD, "full_name": "Stranger"
    })
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 60 * 60 * 24
    claims = decode_token(body["access_token"])
    assert claims and claims["type"] == "access" and claims["sub"].isdigit()


def test_signup_rejects_a_short_password(c):
    assert c.post("/auth/signup", json={
        "email": "x@example.com", "password": "short"
    }).status_code == 422


def test_duplicate_signup_conflicts(c):
    assert c.post("/auth/signup", json={
        "email": STRANGER, "password": PASSWORD
    }).status_code == 409


def test_login_and_me(c):
    r = c.post("/auth/login", json={"email": STRANGER, "password": PASSWORD})
    assert r.status_code == 200
    token = r.json()["access_token"]

    me = c.get("/auth/me", headers=auth(token))
    assert me.status_code == 200
    body = me.json()
    assert set(body) == {
        "id", "email", "full_name", "is_verified", "is_admin", "created_at"
    }
    assert body["email"] == STRANGER
    assert isinstance(body["id"], str)
    assert body["is_admin"] is False


def test_login_with_a_wrong_password_is_401(c):
    assert c.post("/auth/login", json={
        "email": STRANGER, "password": "nope-nope-nope"
    }).status_code == 401


def test_refresh_issues_a_new_access_token(c):
    tokens = c.post("/auth/login", json={
        "email": STRANGER, "password": PASSWORD
    }).json()
    r = c.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    assert decode_token(r.json()["access_token"])["type"] == "access"


def test_an_access_token_cannot_be_used_as_a_refresh_token(c):
    tokens = c.post("/auth/login", json={
        "email": STRANGER, "password": PASSWORD
    }).json()
    assert c.post("/auth/refresh", json={
        "refresh_token": tokens["access_token"]
    }).status_code == 401


def test_a_tampered_token_is_rejected(c):
    token = c.post("/auth/login", json={
        "email": STRANGER, "password": PASSWORD
    }).json()["access_token"]
    head, body, sig = token.split(".")
    forged = f"{head}.{body}.{'A' * len(sig)}"
    assert c.get("/auth/me", headers=auth(forged)).status_code == 401
    assert decode_token(forged) is None


def test_endpoints_require_a_bearer_token(c):
    assert c.get("/auth/me").status_code == 401
    assert c.get("/learning/my-modules").status_code == 401
    assert c.get("/learning/gt-05/progress").status_code == 401


# -----------------------------------------------------------------------------
# Entitlement: one purchase opens all five apps
# -----------------------------------------------------------------------------

def test_without_a_purchase_every_module_is_locked(c):
    token = c.post("/auth/login", json={
        "email": STRANGER, "password": PASSWORD
    }).json()["access_token"]

    assert c.get("/learning/my-modules", headers=auth(token)).json() == []
    for module_id in MODULES:
        r = c.get(f"/learning/{module_id}/access", headers=auth(token))
        assert r.status_code == 200
        assert r.json()["enrolled"] is False
        assert c.get(
            f"/learning/{module_id}/progress", headers=auth(token)
        ).status_code == 403


def test_one_purchase_unlocks_all_five_apps(c):
    """The whole point of the cutover — no per-module grant cascade."""
    r = c.post("/admin/academy/grant".replace("/admin", "/api/admin"), json={
        "email": BUYER, "product_code": PRODUCT,
        "full_name": "Real Buyer", "send_email_invite": False,
    }, headers=ADMIN)
    assert r.status_code == 200

    # The buyer was provisioned without a password. They set one from the
    # magic-link session — not by "signing up" on an email that already carries
    # access, which would let anyone who knows the address take the course.
    token = set_password_then_login(c, BUYER, PASSWORD)

    # One Learner row, not two.
    db = SessionLocal()
    assert db.query(Learner).filter(Learner.email == BUYER).count() == 1
    db.close()

    mods = c.get("/learning/my-modules", headers=auth(token)).json()
    assert [m["module_id"] for m in mods] == ["gt-05", "gt-06", "gt-07", "gt-13", "gt-15"]
    for m in mods:
        assert m["enrolled"] is True
        assert m["url_base"].startswith("https://smallgasturbine.")
        assert set(m) == {
            "module_id", "title", "subtitle", "url_base", "enrolled",
            "granted_at", "last_active_at", "progress_summary", "via_admin",
        }
    for module_id in MODULES:
        assert c.get(
            f"/learning/{module_id}/access", headers=auth(token)
        ).json()["enrolled"] is True


def test_revoking_the_purchase_relocks_every_app(c):
    c.post("/api/admin/academy/revoke",
           json={"email": BUYER, "product_code": PRODUCT}, headers=ADMIN)
    token = c.post("/auth/login", json={
        "email": BUYER, "password": PASSWORD
    }).json()["access_token"]

    assert c.get("/learning/my-modules", headers=auth(token)).json() == []
    assert c.get("/learning/gt-05/progress", headers=auth(token)).status_code == 403

    # Restore for the remaining tests.
    c.post("/api/admin/academy/grant", json={
        "email": BUYER, "product_code": PRODUCT, "send_email_invite": False
    }, headers=ADMIN)


# -----------------------------------------------------------------------------
# Progress round-trip
# -----------------------------------------------------------------------------

def test_progress_payload_round_trips_verbatim(c):
    """The app owns this document; we must not reshape it."""
    token = c.post("/auth/login", json={
        "email": BUYER, "password": PASSWORD
    }).json()["access_token"]

    blob = {
        "sectionState": {
            "s1": {"completedAt": "2026-08-05T10:00:00Z",
                   "probeAttempts": {"p1": [False, True], "p2": [True]}},
            "s2": {"probeAttempts": {"p3": [False, False]}},
        },
        "summative": {"score": 7, "total": 8},
        "needs": {"goal": "apply at work"},
        "weirdNestedThing": [1, {"a": None}, [2, 3]],
    }
    r = c.put("/learning/gt-05/progress", json={"payload": blob}, headers=auth(token))
    assert r.status_code == 200
    assert r.json()["payload"] == blob
    assert r.json()["updated_at"] is not None

    got = c.get("/learning/gt-05/progress", headers=auth(token))
    assert got.json()["payload"] == blob


def test_progress_is_isolated_per_module_and_per_learner(c):
    buyer = c.post("/auth/login", json={
        "email": BUYER, "password": PASSWORD
    }).json()["access_token"]
    c.put("/learning/gt-06/progress", json={"payload": {"only": "gt06"}},
          headers=auth(buyer))

    assert c.get("/learning/gt-06/progress", headers=auth(buyer)).json()["payload"] \
        == {"only": "gt06"}
    assert c.get("/learning/gt-05/progress", headers=auth(buyer)).json()["payload"] \
        != {"only": "gt06"}

    stranger = c.post("/auth/login", json={
        "email": STRANGER, "password": PASSWORD
    }).json()["access_token"]
    # Unentitled, so they cannot even read — let alone see the buyer's blob.
    assert c.get("/learning/gt-06/progress", headers=auth(stranger)).status_code == 403


def test_roster_summary_is_derived_from_the_blob(c):
    token = c.post("/auth/login", json={
        "email": BUYER, "password": PASSWORD
    }).json()["access_token"]
    gt05 = next(m for m in c.get("/learning/my-modules", headers=auth(token)).json()
                if m["module_id"] == "gt-05")
    s = gt05["progress_summary"]
    assert s["sections_completed"] == 1
    assert s["probes_attempted"] == 3
    assert s["probe_accuracy"] == 67  # 2 of 3 eventually correct
    assert s["summative_score"] == "7/8"
    assert s["needs_completed"] is True
    assert gt05["last_active_at"] is not None


def test_unknown_module_is_404(c):
    token = c.post("/auth/login", json={
        "email": BUYER, "password": PASSWORD
    }).json()["access_token"]
    assert c.get("/learning/gt-99/access", headers=auth(token)).status_code == 404
    assert c.get("/learning/gt-99/progress", headers=auth(token)).status_code == 404


def test_request_access_points_an_unentitled_user_at_the_sales_page(c):
    token = c.post("/auth/login", json={
        "email": STRANGER, "password": PASSWORD
    }).json()["access_token"]
    r = c.post("/learning/gt-05/request-access", headers=auth(token))
    assert r.status_code == 201
    assert r.json()["already_enrolled"] is False
    assert r.json()["purchase_url"].endswith(f"/training/{PRODUCT}")


# -----------------------------------------------------------------------------
# Migration path from the old service
# -----------------------------------------------------------------------------

def test_a_migrated_bcrypt_hash_authenticates_unchanged(c):
    """Existing users' password hashes port across verbatim — no reset email."""
    db = SessionLocal()
    legacy = Learner(
        email="legacy@example.com",
        full_name="Legacy User",
        password_hash=hash_password("their-old-password"),
    )
    db.add(legacy)
    db.commit()
    db.close()

    r = c.post("/auth/login", json={
        "email": "legacy@example.com", "password": "their-old-password"
    })
    assert r.status_code == 200
    assert c.get("/auth/me", headers=auth(r.json()["access_token"])).json()["email"] \
        == "legacy@example.com"


def test_compat_tokens_do_not_open_the_academy_or_admin_apis(c):
    """The three auth systems stay separate."""
    token = c.post("/auth/login", json={
        "email": BUYER, "password": PASSWORD
    }).json()["access_token"]
    assert c.get("/api/admin/academy/products", headers=auth(token)).status_code == 401
    # The academy learner API keys off a cookie, not this Bearer token.
    assert c.get("/api/academy/me", headers=auth(token)).json()["signed_in"] is False


# -----------------------------------------------------------------------------
# Owner bypass — the path a password login takes
# -----------------------------------------------------------------------------

def test_owner_password_login_unlocks_every_module_without_a_purchase(c):
    """The bug this pins: the compat layer used to read `is_staff` straight off
    the row, so an owner who only ever signed in here with a password — never
    through an academy magic link — was treated as a stranger and locked out of
    their own material. Entitlement now goes through the config-backed owner
    list, so the DB flag is a cache rather than the source of truth."""
    from app.config import get_settings

    owner_email = get_settings().owner_emails_list[0]

    # Deliberately built the way a pre-existing account looks: a password, and
    # is_staff still False because nothing has promoted it yet. (The row may
    # already exist from the academy suite — same shared DB — so this reshapes
    # it rather than insisting on inserting.)
    db = SessionLocal()
    row = db.query(Learner).filter(Learner.email == owner_email).one_or_none()
    if row is None:
        row = Learner(email=owner_email, full_name="Owner")
        db.add(row)
    row.password_hash = hash_password("owners-own-password")
    row.is_staff = False
    db.commit()
    db.close()

    r = c.post(
        "/auth/login", json={"email": owner_email, "password": "owners-own-password"}
    )
    assert r.status_code == 200
    token = r.json()["access_token"]

    assert c.get("/auth/me", headers=auth(token)).json()["is_admin"] is True

    mods = c.get("/learning/my-modules", headers=auth(token)).json()
    assert len(mods) == len(MODULES), "owner should see every module"
    assert all(m["enrolled"] for m in mods)
    assert all(m["via_admin"] for m in mods), "and be marked as reaching them as admin"

    for module_id in MODULES:
        access = c.get(f"/learning/{module_id}/access", headers=auth(token)).json()
        assert access["enrolled"] is True
        assert access["is_admin"] is True


def test_owner_email_cannot_be_claimed_by_password_signup(c):
    """An address that grants everything must not be claimable by whoever
    types it first — it takes the email-link route, which proves the mailbox."""
    from app.config import get_settings

    r = c.post(
        "/auth/signup",
        json={
            "email": get_settings().owner_emails_list[0].upper(),
            "password": "not-your-account",
            "full_name": "Impostor",
        },
    )
    assert r.status_code == 403
    assert "link" in r.json()["detail"].lower()


def test_a_paid_account_without_a_password_cannot_be_claimed_by_a_stranger(c):
    """A Stripe buyer's row sits password-less until they set one. Signing up
    on that email used to adopt the row — and the course with it."""
    db = SessionLocal()
    db.add(Learner(email="paid-no-password@example.com", full_name="Buyer"))
    db.commit()
    db.close()

    r = c.post(
        "/api/admin/academy/grant",
        headers=ADMIN,
        json={
            "email": "paid-no-password@example.com",
            "product_code": PRODUCT,
            "send_email_invite": False,
        },
    )
    assert r.status_code == 200

    r = c.post(
        "/auth/signup",
        json={"email": "paid-no-password@example.com", "password": "stolen-account"},
    )
    assert r.status_code == 403
    assert c.post(
        "/auth/login",
        json={"email": "paid-no-password@example.com", "password": "stolen-account"},
    ).status_code == 401


# -----------------------------------------------------------------------------
# Password recovery — the apps have no reset screen, so the route rides in the
# refusal text they display
# -----------------------------------------------------------------------------

RESET_PATH = "/learn/signin?reason=password"


def test_wrong_password_refusal_carries_the_reset_route(c):
    r = c.post("/auth/login", json={"email": STRANGER, "password": "nope-nope-nope"})
    assert r.status_code == 401
    assert RESET_PATH in r.json()["detail"]
    assert "Forgot it?" in r.json()["detail"]


def test_paid_account_without_a_password_is_told_how_to_set_one(c):
    db = SessionLocal()
    db.add(Learner(email="paid-forgot@example.com", full_name="Buyer"))
    db.commit()
    db.close()
    assert c.post(
        "/api/admin/academy/grant", headers=ADMIN,
        json={"email": "paid-forgot@example.com", "product_code": PRODUCT, "send_email_invite": False},
    ).status_code == 200

    r = c.post("/auth/login", json={"email": "paid-forgot@example.com", "password": "anything-at-all"})
    assert r.status_code == 401
    assert "no password yet" in r.json()["detail"]
    assert RESET_PATH in r.json()["detail"]

    r = c.post("/auth/signup", json={"email": "paid-forgot@example.com", "password": "anything-at-all"})
    assert r.status_code == 403
    assert RESET_PATH in r.json()["detail"]


def test_set_password_replaces_a_forgotten_one(c):
    """The recovery path end to end: a learner who set a password and lost it
    signs in by email link and sets a new one; the old one stops working."""
    email = "forgetful@example.com"
    assert c.post(
        "/api/admin/academy/grant", headers=ADMIN,
        json={"email": email, "product_code": PRODUCT, "send_email_invite": False},
    ).status_code == 200
    set_password_then_login(c, email, "first-password-1")
    set_password_then_login(c, email, "second-password-2")
    assert c.post("/auth/login", json={"email": email, "password": "first-password-1"}).status_code == 401
    assert c.post("/auth/login", json={"email": email, "password": "second-password-2"}).status_code == 200
