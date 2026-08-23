"""The download counter must keep counting past two digits.

Asked directly whether the counter was "pegged at 99", the honest answer came
from reading the code — every count is a live SELECT COUNT(*), and every
display path runs the value through toLocaleString(). Nothing truncates. But
"I read the code and it looks fine" is a weaker answer than a test that walks
the number past the suspected ceiling and checks what comes out, so here it is.

Also pins the boundary values a capped implementation would trip on: 99, 100,
and a five-figure count.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app

from app.models import ProductDownload, SoftwareProduct

SLUG = "counter-scale-test"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def product(db):
    row = db.execute(
        select(SoftwareProduct).where(SoftwareProduct.slug == SLUG)
    ).scalar_one_or_none()
    if row is None:
        row = SoftwareProduct(
            slug=SLUG, name="Counter Scale Test", asset_path="/downloads/x.zip",
            latest_version="1.0.0", status="live",
        )
        db.add(row)
        db.commit()
    yield row
    for d in db.execute(
        select(ProductDownload).where(ProductDownload.product == SLUG)
    ).scalars().all():
        db.delete(d)
    db.delete(row)
    db.commit()


def _seed(db, n: int) -> None:
    """n downloads, all recent enough to land inside the 7- and 30-day windows.

    Spaced by seconds, not minutes: at minute spacing a five-figure seed would
    stretch back over a week and the window counts would legitimately differ
    from the total, testing the clock instead of the counter.
    """
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            ProductDownload(
                product=SLUG,
                ts=now - timedelta(seconds=i),
                country="US",
                referrer="https://proreadyengineer.com/products",
            )
            for i in range(n)
        ]
    )
    db.commit()


@pytest.mark.parametrize("n", [1, 99, 100, 101, 12_345])
def test_public_counter_reports_the_real_total(client, db, product, n):
    _seed(db, n)
    body = client.get(f"/api/downloads/stats?product={SLUG}").json()
    assert body["total"] == n, f"counter reported {body['total']} for {n} downloads"
    assert body["last7"] == n
    assert body["last30"] == n


@pytest.mark.parametrize("n", [99, 100, 12_345])
def test_software_list_counter_reports_the_real_total(client, db, product, n):
    _seed(db, n)
    row = next(
        p for p in client.get("/api/products/software").json() if p["slug"] == SLUG
    )
    assert row["download_count"] == n


def test_admin_view_counts_past_the_recent_events_window(client, db, product):
    """The admin view lists only the 100 most recent events. That cap must not
    leak into the totals — which is exactly the shape a "stuck at 99" bug takes.
    """
    from tests.conftest import ADMIN_TOKEN

    _seed(db, 250)
    body = client.get(
        f"/api/admin/downloads?product={SLUG}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    ).json()
    assert body["total"] == 250
    assert body["last30"] == 250
    assert len(body["recent"]) == 100, "the recent list is capped by design"
    assert sum(d["count"] for d in body["by_day"]) == 250, (
        "the daily histogram must account for every download, not just the "
        "hundred the recent list shows"
    )
