"""The auth dependencies must hand their DB connection back before the
endpoint runs.

FastAPI runs each sync dependency and the endpoint as separate hops on one
40-thread pool. A dependency that keeps its connection while its request
queues for the next hop lets a burst of requests (a phone opening a deck's
thumbnail strip) tie up every thread waiting for connections held by
requests waiting for threads: the API stalled for 30 s at a time and
answered with 500s (2026-09-16 to -19). Reproduced locally with the pool and
thread limit scaled down 1:1 (78 of 92 thumbnails failed, /healthz stalled
78 s); with the release in place the same burst, three at once, all pass.
"""
from __future__ import annotations

import asyncio
import base64

import anyio
import httpx
import conftest  # noqa: F401
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from starlette.requests import Request

from app import db as dbm
from app.db import SessionLocal
from app.learner_auth import make_learner_token, optional_learner
from app.main import app  # noqa: F401  (creates the tables)
from app.models import Learner
from app.routes.compat import _token_response, current_learner


def _learner() -> Learner:
    db = SessionLocal()
    try:
        row = db.query(Learner).filter(Learner.email == "pool.release@example.com").one_or_none()
        if row is None:
            row = Learner(email="pool.release@example.com", full_name="Pool Release")
            db.add(row)
            db.commit()
            db.refresh(row)
        db.expunge(row)
        return row
    finally:
        db.close()


def _request() -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": [],
        "client": ("203.0.113.9", 1234), "query_string": b"",
    })


def _check(db, learner) -> None:
    # The transaction is over, so the pooled connection is back in the pool…
    assert not db.in_transaction()
    # …and the learner is still loaded: the endpoint reads it without
    # another round trip.
    state = inspect(learner)
    assert not state.expired_attributes
    assert state.dict["email"] == "pool.release@example.com"
    assert not db.in_transaction()


def test_learner_cookie_dependency_releases_its_connection():
    who = _learner()
    token = make_learner_token(who.id, who.email)
    db = SessionLocal()
    try:
        # First call: a new browser, registered with a write that commits.
        learner = optional_learner(_request(), Response(), learner_session=token,
                                   learner_device="a" * 32, db=db)
        assert learner is not None
        assert not db.in_transaction()
        # Second call: the common read-only path — the one that used to
        # keep its connection checked out across the hop.
        learner = optional_learner(_request(), Response(), learner_session=token,
                                   learner_device="a" * 32, db=db)
        _check(db, learner)
        assert learner.id == who.id
    finally:
        db.close()


def test_unknown_learner_still_releases():
    db = SessionLocal()
    try:
        token = make_learner_token(987654321, "nobody@example.com")
        assert optional_learner(_request(), Response(), learner_session=token,
                                learner_device="", db=db) is None
        assert not db.in_transaction()
    finally:
        db.close()


def test_quiz_app_bearer_dependency_releases_its_connection():
    who = _learner()
    access = _token_response(who).access_token
    db = SessionLocal()
    try:
        learner = current_learner(authorization=f"Bearer {access}", db=db)
        assert learner.id == who.id
        _check(db, learner)
    finally:
        db.close()


def test_a_burst_of_thumbnails_does_not_stall_the_api():
    """The incident itself, scaled down 1:1 (4 connections, 4 threads): forty
    thumbnail requests arriving together. Before the fix every thread ended
    up waiting for a connection held by a request waiting for a thread, and
    36 of 40 failed after the pool timeout."""
    admin = {"Authorization": f"Bearer {conftest.ADMIN_TOKEN}"}
    email = "burst.phone@example.com"
    with TestClient(app, base_url="https://testserver") as c:
        c.post("/api/admin/academy/products", headers=admin, json={
            "code": "burst-test", "title": "Burst test", "sequential_gate": False, "status": "draft"})
        mid = c.post("/api/admin/academy/products/burst-test/modules", headers=admin,
                     json={"code": "D1", "title": "Day 1", "position": 1}).json()["module_id"]
        png = base64.b64encode(bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
            "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()
        r = c.post(f"/api/admin/academy/modules/{mid}/slides", headers=admin, json={"slides": [
            {"number": 1, "title": "S1", "image_sm_b64": png, "image_lg_b64": png}]})
        assert r.status_code == 200, r.text
        c.post("/api/admin/academy/grant", headers=admin, json={
            "email": email, "product_code": "burst-test", "send_email_invite": False})
        link = c.post("/api/admin/academy/login-link", headers=admin, json={"email": email}).json()["link"]
        v = c.post("/api/academy/auth/verify", json={"token": link.split("token=")[1]})
        assert v.status_code == 200
        cookies = {k: v.cookies[k] for k in ("learner_session", "learner_device")}

    small = create_engine(dbm.db_url, pool_size=2, max_overflow=2, pool_timeout=2,
                          connect_args={"check_same_thread": False})
    original = dbm.SessionLocal.kw["bind"]
    dbm.SessionLocal.configure(bind=small)

    async def burst():
        anyio.to_thread.current_default_thread_limiter().total_tokens = 4
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="https://testserver", cookies=cookies) as client:
            return await asyncio.gather(
                *[client.get(f"/api/academy/slide-image/{mid}/1/sm") for _ in range(40)],
                return_exceptions=True)

    try:
        results = asyncio.run(burst())
    finally:
        dbm.SessionLocal.configure(bind=original)
        small.dispose()
    failures = [r for r in results if not (isinstance(r, httpx.Response) and r.status_code == 200)]
    assert not failures, f"{len(failures)} of 40 failed: {failures[:1]}"
