"""Humanizing anti-bot-stealth layer.

Cloudflare (and the CF API edge) throttle or ban accounts whose automation
looks machine-generated: metronomic timing with zero delay between sequences of
calls, fixed-interval retries, and byte-identical request cadence. This module
adds randomized, human-shaped pacing and jitter to every API interaction so the
console reads like a careful human operator rather than a script.

We are *not* evading authentication — this is a legitimate automated console
that should behave gently so it does not trip bulk-rate heuristics (the user
reports their Cloudflare account gets banned when running autopilot).

Everything is configurable and can be disabled entirely with the env var
``KHVARENAH_STEALTH=0`` (used by tests / CI).

Principles
----------
* Delay *before* a call, like a person loading a page — never a fixed clock.
* Reads/list calls pause short (lookup latency); writes/deploys pause longer
  (the "crafting" step).
* ~8% of calls take an extra "distraction" pause so long runs never look
  metronome-perfect.
* Retry backoff is exponential but jittered (never lockstep).
* Everything uses one module-level RNG; no urandom churn per call.
"""

from __future__ import annotations

import os
import random
import time

_ENABLED = os.environ.get("KHVARENAH_STEALTH", "1") != "0"
_rng = random.Random()  # seeded from system entropy at import


def enabled() -> bool:
    return _ENABLED


def _sleep(seconds: float) -> None:
    if _ENABLED and seconds > 0:
        time.sleep(seconds)


def jitter(low: float, high: float) -> float:
    """Uniform random value in [low, high]."""
    return _rng.uniform(low, high)


def pre_request_pause(kind: str = "read") -> None:
    """Human-shaped pause before an API call.

    kind="read"  -> short delay (~0.4–2.0s), like a lookup.
    kind="write" -> longer "crafting" delay (~1.5–4.5s).
    ~8% of the time add an extra "distraction" pause (1.5–6s) so long runs
    never read as perfectly periodic.
    """
    if not _ENABLED:
        return
    if kind == "write":
        base = jitter(1.5, 4.5)
    else:
        base = jitter(0.4, 2.0)
    if _rng.random() < 0.08:
        base += jitter(1.5, 4.5)
    _sleep(base)


def boundary_pause(min_s: float = 0.5, max_s: float = 2.5) -> None:
    """Pause between major workflow stages (e.g. deploy -> scan).

    This is the "read the output, think, move on" gap a human leaves between
    distinct operations.  Default is short enough to stay snappy but varied.
    """
    _sleep(jitter(min_s, max_s))


def retry_backoff(attempt: int) -> None:
    """Randomized exponential backoff between retries.

    ``attempt`` is 0-based.  Roughly ``2**(attempt+1)`` seconds scaled by a
    0.75–1.25 jitter factor, floored at 1.0s so the first retry is never
    instant (which itself looks scripted).
    """
    exp = 2.0 ** (attempt + 1)
    _sleep(max(1.0, exp * jitter(0.75, 1.25)))
