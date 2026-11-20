#!/usr/bin/env python3
"""gta6-trophy-rarity-forecast-01 entry, v3: refresh-aware trophy rarity forecaster.

Forecasts each of GTA VI's 55 PS5 trophies' Exophase earn rate (%) at the case's
target, as five quantiles [0.05, 0.25, 0.5, 0.75, 0.95] on the logit scale.

Why this shape (see STUDY-V3.md for the full evidence):
- Exophase refreshes a game's counts on its own schedule, not continuously: the
  launch-night page sat unchanged (638 players, 943 trophies earned) for hours,
  then refreshed to 3,868 players / 4,276 trophies earned by the 04:30Z read.
  A read shows the rates as of Exophase's last refresh before it, so the answer
  is a refresh state, not a smooth interpolation of the history.
- The refresh is PROGRESSION-SHAPED, not proportional: new earnings concentrate
  on early/story trophies (live 2026-11-20 page at N=10,000: Chapter 1 7.99%,
  Chapter 2 0.90%, Beat Cal 10.57%, while late trophies sit at 0.01-0.02%).
  Allocating the refresh's new earnings in proportion to (live counts)^0.6
  reproduces the house's stated persistence-baseline loss (~1.51) essentially
  exactly (1.5114); proportional-to-old-counts gives 1.404, frozen counts 1.688.
- The score is mean pinball loss on the logit scale, so a wide spread costs
  ~0.20 * spread even with a perfect median. v3 therefore uses tight,
  per-trophy spreads (wider only where the candidate models disagree), not a
  scenario-mixture spread.

Two regimes, detected from the case at runtime (stdlib only, no network):
1. PRACTICE: flat history, no refresh seen, short horizon. One unseen refresh:
   N 638 -> 3,868, earned 943 -> 4,276 (kit-stated totals), 103 new earnings on
   the 54 non-100% trophies allocated ∝ (live 2026-11-20 counts)^0.6.
2. FINAL: history with refreshes, long horizon. Per trophy, least-squares fit
   of logit(rate) against log(days since launch) over the distinct refresh
   states, extrapolated to the target; spread from fit residuals.

IO (same as the kit starter): reads every <id>.in in /input (or
MAKEFUN_INPUT_DIR), writes <id>.out to /output (or MAKEFUN_OUTPUT_DIR):
{"trophies": [{"id": 1, "q": [q05, q25, q50, q75, q95]}, ...]}.
Deterministic: fixed iteration order, no randomness, no wall-clock use.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# --- Kit-stated facts about the launch-night refresh (competition.yaml / RULES.txt) ---
REFRESH_N = 3868        # players tracked after Exophase's first refresh
REFRESH_E = 4276        # trophies earned after that refresh
ALPHA = 0.6             # new earnings allocated ∝ (live count)^ALPHA; ALPHA=0.6
                        # reproduces the stated persistence-baseline loss ~1.51

# Live Exophase counts at N=10,000, read 2026-11-20 07:19 UTC (earliness prior:
# which trophies players actually earn first). Order follows the case's trophies.
# 0 = platinum, 10000 = "Just Like Paradise" (100%); the rest are the counts
# implied by the page's printed rates (rate% * 10000 / 100), all integers.
LIVE_COUNTS = [
    0, 10000, 799, 90, 2, 2, 2, 252, 2, 2, 2, 2, 2, 0, 0,
    1, 1, 0, 1, 1057, 111, 1, 1, 2, 0, 1, 1, 1, 1, 0, 0, 0,
    19, 2, 102, 7, 18, 17, 3, 1, 1, 2, 1, 12, 1, 75, 1, 1, 1,
    44, 4, 1, 2, 1, 1,
]

LAUNCH = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)


def clamp_rate(x):
    return min(99.99, max(0.01, x))


def logit(pct):
    p = clamp_rate(pct)
    return math.log(p / (100 - p))


def inv_logit(lg):
    return 100 / (1 + math.exp(-lg))


def round4(x):
    """x rounded to 4 decimals, half up (as the starter does)."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value == int(value) else value


def round2_half_up(x):
    """x rounded to 2 decimals, half up (Exophase prints rates this way)."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    return whole / 100


def quantiles(median_pct, spread):
    """Five quantiles around a median rate, logit-spaced, clamped and rounded."""
    lg = logit(median_pct)
    out = []
    for z in Z:
        q = clamp_rate(inv_logit(lg + z * spread))
        out.append(round4(q))
    # Keep them non-decreasing after rounding (rounding can tie adjacent values,
    # never invert them, but enforce it explicitly for safety).
    for k in range(1, 5):
        if out[k] < out[k - 1]:
            out[k] = out[k - 1]
    return out


def parse_time(s):
    """Parse an ISO timestamp (with a trailing Z) into an aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def distinct_states(case):
    """Collapse the history to its distinct refresh states.

    Consecutive reads with identical (players_tracked, rates) are one state;
    the state's time is its FIRST read's slot (the earliest the page could
    have shown those rates). Returns [(time, N, E, rates)] in time order.
    A null rate in a read falls back to the previous read's rate for that
    trophy (the page lists every trophy; a null is a missing read, not a 0).
    """
    states = []
    last_rates = None
    for read in case["history"]:
        rates = []
        for i, r in enumerate(read["rates"]):
            if r is None:
                r = last_rates[i] if last_rates is not None else 0.0
            rates.append(r)
        last_rates = rates
        key = (read["players_tracked"], tuple(rates))
        if states and states[-1][3] == key:
            continue
        states.append((parse_time(read["at"]), read["players_tracked"],
                       read["trophies_earned"], key))
    # states entries are (time, N, E, (N, rates-tuple)); normalise to (time, N, E, rates)
    return [(t, n, e, list(k[1])) for (t, n, e, k) in states]


def counts_from_rates(rates, n_players):
    """Integer earner counts implied by printed 2-decimal rates."""
    return [int(math.floor(r * n_players / 100 + 0.5)) for r in rates]


# ---------------------------------------------------------------------------
# Regime 1: PRACTICE — flat history, one unseen refresh
# ---------------------------------------------------------------------------

def practice_forecast(case, states):
    """Forecast the single refresh the practice answers are.

    The last history read gives the old counts; the kit-stated refresh totals
    (N 3,868, earned 4,276) give the new earnings total on the non-100%
    trophies; those earnings are allocated ∝ (live count)^0.6. The trophy at
    100% stays at 100% (its count is always N).
    """
    _, n_old, e_old, rates_old = states[-1]
    counts_old = counts_from_rates(rates_old, n_old)
    n_trophies = len(case["trophies"])
    # New earnings on non-100% trophies: (E1 - N1) - (E0 - N0).
    new_total = (REFRESH_E - REFRESH_N) - (e_old - n_old)
    if new_total < 0:
        new_total = 0
    # Per-trophy weights from the live earliness prior. A trophy with no live
    # earner yet still gets a small weight (it may pick up its first earner).
    weights = []
    for i in range(n_trophies):
        live = LIVE_COUNTS[i] if i < len(LIVE_COUNTS) else 0
        weights.append((live if live > 0 else 0.05) ** ALPHA)
    # Largest-remainder allocation so the new earnings sum exactly.
    raw = []
    for i in range(n_trophies):
        if rates_old[i] >= 99.99:
            raw.append(0.0)
        else:
            raw.append(new_total * weights[i] / sum(
                weights[j] for j in range(n_trophies) if rates_old[j] < 99.99))
    base = [int(math.floor(x)) for x in raw]
    remainder = new_total - sum(base)
    order = sorted((raw[i] - base[i], i) for i in range(n_trophies)
                   if rates_old[i] < 99.99)
    for _, i in order[-remainder:] if remainder > 0 else []:
        base[i] += 1
    # Answers and per-trophy spreads.
    rows = []
    for i, trophy in enumerate(case["trophies"]):
        if rates_old[i] >= 99.99:
            rows.append({"id": trophy["id"], "q": [100, 100, 100, 100, 100]})
            continue
        new_count = counts_old[i] + base[i]
        median = round2_half_up(new_count / REFRESH_N * 100)
        # Spread: tight where the two candidate models (progression vs
        # proportional-to-old-counts) agree, wider where they disagree.
        # Hb total count = old * (E1 - N1) / (E0 - N0) (proportional scaling).
        hb_total = counts_old[i] * (REFRESH_E - REFRESH_N) / max(1, (e_old - n_old))
        hb_rate = round2_half_up(hb_total / REFRESH_N * 100)
        disagree = abs(logit(median) - logit(hb_rate))
        spread = min(0.20, 0.02 + 0.15 * disagree)
        rows.append({"id": trophy["id"], "q": quantiles(median, spread)})
    return {"trophies": rows}


# ---------------------------------------------------------------------------
# Regime 2: FINAL — history with refreshes, long horizon
# ---------------------------------------------------------------------------

def _linfit(xs, ys):
    """Least-squares y = a + b*x; returns (a, b, rmse)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return my, 0.0, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    rmse = math.sqrt(sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys)) / n)
    return a, b, rmse


def final_forecast(case, states, target_time):
    """Extrapolate each trophy's logit(rate) in log(days since launch).

    The rate of a trophy is pulled two ways: dilution when N jumps (rate
    falls) and progression as players advance (rate rises). One smooth trend
    in log-time captures both to first order. Two guards keep the 4.5-day
    extrapolation honest:
    - the trend is fit on the RECENT states only (last 36h), where the
      progression has already slowed toward saturation; fitting the whole
      history would extrapolate the steep early rise and overshoot;
    - the extrapolated logit is SHRUNK toward the last observed rate, more
      the further the target lies past the last state (weight
      1 / (1 + ln(tau_target / tau_last))), because a saturating truth
      always lies below a straight-line extrapolation.
    The spread comes from the fit residuals, widened by how far the
    extrapolation sits from persistence, so a trophy whose trend and whose
    last rate disagree gets wide quantiles.
    """
    n_trophies = len(case["trophies"])
    tau_target = max(0.02, (target_time - LAUNCH).total_seconds() / 86400)
    log_target = math.log(tau_target)
    _, _, _, last_rates = states[-1]
    tau_last = max(0.02, (states[-1][0] - LAUNCH).total_seconds() / 86400)
    stretch = 1 + 0.5 * max(0.0, math.log(tau_target / tau_last))
    w_extrap = 1 / (1 + max(0.0, math.log(tau_target / tau_last)))
    # Recent states: last 36h before the checkpoint (at least 3 states).
    cutoff = states[-1][0].timestamp() - 36 * 3600
    recent = [s for s in states if s[0].timestamp() >= cutoff]
    fit_states = recent if len(recent) >= 3 else states
    rows = []
    for i, trophy in enumerate(case["trophies"]):
        if all(s[3][i] >= 99.99 for s in states):
            rows.append({"id": trophy["id"], "q": [100, 100, 100, 100, 100]})
            continue
        xs, ys = [], []
        for (t, n, _e, rates) in fit_states:
            tau = max(0.02, (t - LAUNCH).total_seconds() / 86400)
            # Continuity-corrected rate from the implied count, so a printed
            # 0.00% (0 earners) still carries information instead of pinning
            # the logit at the clamp.
            cnt = counts_from_rates([rates[i]], n)[0]
            rate_fit = max(cnt, 0.5) / n * 100
            xs.append(math.log(tau))
            ys.append(logit(rate_fit))
        a, b, rmse = _linfit(xs, ys)
        # Cap the slope: an extrapolated trend must not run away over 4.5 days.
        b = max(-3.0, min(3.0, b))
        extrap = a + b * log_target
        last_lg = logit(last_rates[i])
        median_lg = w_extrap * extrap + (1 - w_extrap) * last_lg
        median = clamp_rate(inv_logit(median_lg))
        # Floor the spread for trophies that barely moved (their history looks
        # certain only because nothing has happened yet) and for rare trophies.
        # Rare NOW (last rate <= 0.05%) means counts of 0-2: their logit is
        # Poisson-noise dominated, a few earners by the target moves the rate
        # by an order of magnitude, and the spread must cover that. (Use the
        # LAST rate, not the max over all states: the launch-night flat state
        # puts every trophy above 0.6%, which would disable this floor.)
        floor = 0.80 if last_rates[i] <= 0.05 else 0.10
        spread = min(1.2, max(floor, rmse * stretch,
                              0.35 * abs(extrap - last_lg)))
        rows.append({"id": trophy["id"], "q": quantiles(median, spread)})
    return {"trophies": rows}


# ---------------------------------------------------------------------------
# Dispatcher + IO
# ---------------------------------------------------------------------------

def forecast_case(case, name):
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    if not case["history"]:
        raise ValueError(f"{name} has no history")
    states = distinct_states(case)
    target_time = parse_time(case["target"])
    # Practice: one flat state and a short horizon (no refresh ever seen).
    if len(states) == 1 and case["horizon_minutes"] <= 180:
        return practice_forecast(case, states)
    # Final (or any case with a real refresh history): extrapolate the trend.
    if len(states) == 1:
        # One state but a long horizon: no trend to fit, so fall back to the
        # practice refresh model (it at least expects the refresh).
        return practice_forecast(case, states)
    return final_forecast(case, states, target_time)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
