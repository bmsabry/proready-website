"""Business-day settlement window for delayed-notification payments (ACH).

US bank debits confirm days after checkout: `checkout.session.completed`
arrives with payment_status='unpaid', and the money is only certain when
`checkout.session.async_payment_succeeded` (or _failed) lands 4-5 business
days later. Access granted at checkout is therefore provisional, with this
margin as the drop-dead date: a pending enrollment whose deadline passes
without confirmation is revoked (see academy.settlement_ok).
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Stripe says 4-5 business days for ACH; 7 leaves a margin for bank holidays
# and slow rails before provisional access is pulled.
SETTLEMENT_MARGIN_BUSINESS_DAYS = 7


def add_business_days(dt: datetime, n: int) -> datetime:
    """`dt` plus `n` business days, skipping Saturdays and Sundays.

    Counts whole days forward, keeping the time-of-day; a weekend start
    simply rolls onto the following weekdays (Sat + 1 business day = Mon).
    """
    result = dt
    remaining = int(n)
    while remaining > 0:
        result += timedelta(days=1)
        if result.weekday() < 5:  # Mon..Fri
            remaining -= 1
    return result
