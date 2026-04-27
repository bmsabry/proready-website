"""Conservative token-cost estimator for the daily spend cap.

Different providers price tokens differently. Rather than maintain a
per-model price table (which goes stale), we use single conservative
defaults that overestimate cost across the popular OpenAI-compatible
models. The cap is a SAFETY mechanism, not an invoice — it just needs
to fail closed before the bill gets out of hand.

Defaults are higher than Gemini Flash, GPT-4o-mini, Claude Haiku, etc.
If the admin uses a costlier model, the cap will trip earlier than the
real bill suggests — that's fine, they can raise it.

Costs are tracked in micro-dollars (1e-6 USD) so we can use plain ints
and never float-rounding-error our way past the cap.
"""
from __future__ import annotations

# $ per million tokens (conservative — overshoots the cheap tier).
DEFAULT_INPUT_USD_PER_M = 0.50
DEFAULT_OUTPUT_USD_PER_M = 1.50

# $5/day cap converted to micro-dollars.
DEFAULT_DAILY_CAP_MICRO_USD = 5 * 1_000_000


def estimate_cost_micro(tokens_in: int, tokens_out: int) -> int:
    """Return cost estimate in micro-dollars (USD * 1e6)."""
    return int(
        (tokens_in * DEFAULT_INPUT_USD_PER_M / 1_000_000 * 1_000_000)
        + (tokens_out * DEFAULT_OUTPUT_USD_PER_M / 1_000_000 * 1_000_000)
    )


def format_micro_usd(micro: int) -> str:
    """'1234567' -> '$1.23'."""
    return f"${micro / 1_000_000:.2f}"
