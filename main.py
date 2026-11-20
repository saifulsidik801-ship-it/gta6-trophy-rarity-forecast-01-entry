#!/usr/bin/env python3
"""GTA VI trophy rarity forecaster (v5) -- final-target trend model.

Method (see STUDY-V5.md; spec: FINAL-WAY-ANALYSIS.md section 4):
  1. Collapse the case history to distinct refresh states.
  2. Drop the launch-night flat state (the pre-refresh population) and
     any state before the first refresh: it is a different (reviewer)
     population and poisons the fit.
  3. Per trophy, over the LAST 3 distinct states, least-squares fit
     logit(rate) = a + b*ln(1+t), t = hours since 2026-11-19T00:00Z,
     with a 0.5-count continuity correction
     rate_adj = (E + 0.5) / (N + 1) * 100, E = rate * N / 100.
  4. Shrink the slope: beta = median b over trophies with max rate >= 1%
     in the used states; b <- 0.5*b + 0.5*beta; re-centre
     a = mean(logit - b*x).
  5. Median: the shrunk line read at the case target.
  6. Spread: s = sqrt((0.5*sqrt(d))^2 + s_res^2) * 0.85, d = horizon in
     days (target - checkpoint), s_res = residual SD of the shrunk fit
     (floor 0.15). Quantiles q_tau = inv_logit(logit(med) + z_tau*s),
     z = (-1.645, -0.674, 0, 0.674, 1.645).
  7. Low-signal: trophies whose max rate across the used states is
     < 0.10% get their median floored at 0.10% and spread at 0.8.
  8. A trophy at 100% stays 100%. Clamp everything to [0.01, 99.99].

Fewer than 3 distinct states after the drop -> persistence + random-walk
spread (the house baseline): the practice cases land here, by design --
the practice is a refresh straddle, not a trend, and this program is
built for the final (Nov 26 target), not for the practice.

Stdlib only, deterministic, no network.
"""
import json
import math
import os
from datetime import datetime, timezone

EPOCH = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)
Z = (-1.645, -0.674, 0.0, 0.674, 1.645)


def parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def logit_pct(rate):
    p = min(max(rate, 0.01), 99.99) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit_pct(x):
    if x >= 0.0:
        return 100.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return 100.0 * e / (1.0 + e)


def clamp_pct(v):
    return min(max(v, 0.01), 99.99)


def median_of(values):
    vals = sorted(values)
    n = len(vals)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return vals[n // 2]
    return 0.5 * (vals[n // 2 - 1] + vals[n // 2])


def distinct_states(history):
    """Collapse consecutive identical reads to distinct refresh states."""
    states = []
    prev_key = None
    for read in history:
        key = (read.get("players_tracked"), read.get("trophies_earned"),
               tuple(read.get("rates") or []))
        if key != prev_key:
            states.append(read)
            prev_key = key
    return states


def fit_line(xs, ys):
    """Least squares y = a + b*x. Returns (a, b)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0.0:
        return my, 0.0
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = num / den
    return my - b * mx, b


def quantiles_from(med, spread):
    """Five quantiles around a median at a logit spread, clamped, ordered."""
    base = logit_pct(med)
    qs = [round(clamp_pct(inv_logit_pct(base + z * spread)), 4) for z in Z]
    for i in range(1, len(qs)):
        if qs[i] < qs[i - 1]:
            qs[i] = qs[i - 1]
    return qs


def persistence_row(last_rate, horizon_days):
    """House baseline: median = last rate, random-walk spread."""
    if last_rate >= 100.0:
        return [100.0, 100.0, 100.0, 100.0, 100.0]
    spread = 0.5 * math.sqrt(max(horizon_days, 0.0))
    return quantiles_from(last_rate, spread)


def forecast_case(case):
    trophies = case["trophies"]
    history = case.get("history") or []
    at = parse_ts(case["at"])
    target = parse_ts(case["target"])
    horizon_days = (target - at).total_seconds() / 86400.0
    t_target = max((target - EPOCH).total_seconds() / 3600.0, 0.0)
    x_target = math.log1p(t_target)

    # Last rate per trophy, from the last history read.
    last_rates = {}
    if history:
        last_read = history[-1]
        last_list = last_read.get("rates") or []
        for i, tr in enumerate(trophies):
            rate = last_list[i] if i < len(last_list) else None
            last_rates[tr["id"]] = rate if rate is not None else 0.01

    states = distinct_states(history)
    # Drop the pre-refresh state(s): the first distinct state, when a
    # later state differs from it, is the launch-night flat population.
    # With a single distinct state there was no refresh at all, so it is
    # the flat state too and nothing remains to fit on.
    if len(states) >= 2:
        states = states[1:]
    else:
        states = []

    rows = []
    if len(states) < 3:
        # Not enough distinct post-refresh states to fit a trend:
        # persistence + random-walk spread (house baseline).
        for tr in trophies:
            rows.append({"id": tr["id"],
                         "q": persistence_row(last_rates.get(tr["id"], 0.01),
                                              horizon_days)})
        return {"trophies": rows}

    used = states[-3:]

    # Per-trophy fit points over the used states.
    series = {}
    for idx, tr in enumerate(trophies):
        pts = []
        for st in used:
            rates = st.get("rates") or []
            rate = rates[idx] if idx < len(rates) else None
            if rate is None:
                continue
            n_players = st.get("players_tracked") or 0
            if n_players <= 0:
                continue
            earners = rate * n_players / 100.0
            rate_adj = (earners + 0.5) / (n_players + 1.0) * 100.0
            t_hours = max((parse_ts(st["at"]) - EPOCH).total_seconds()
                          / 3600.0, 0.0)
            pts.append((math.log1p(t_hours), logit_pct(rate_adj), rate))
        series[tr["id"]] = pts

    # Raw least-squares slopes, then the shared slope beta.
    slopes = {}
    for tid, pts in series.items():
        if len(pts) >= 2:
            _, b = fit_line([p[0] for p in pts], [p[1] for p in pts])
            slopes[tid] = b
    strong = [slopes[tid] for tid, pts in series.items()
              if tid in slopes and max(p[2] for p in pts) >= 1.0]
    if strong:
        beta = median_of(strong)
    elif slopes:
        beta = median_of(list(slopes.values()))
    else:
        beta = 0.0

    rw = 0.5 * math.sqrt(max(horizon_days, 0.0))
    for tr in trophies:
        tid = tr["id"]
        last = last_rates.get(tid, 0.01)
        if last >= 100.0:
            rows.append({"id": tid, "q": [100.0, 100.0, 100.0, 100.0, 100.0]})
            continue
        pts = series.get(tid, [])
        if len(pts) < 2 or tid not in slopes:
            rows.append({"id": tid,
                         "q": persistence_row(last, horizon_days)})
            continue
        # Shrink the slope halfway toward the shared slope, re-centre.
        b_shrunk = 0.5 * slopes[tid] + 0.5 * beta
        a_shrunk = sum(p[1] - b_shrunk * p[0] for p in pts) / len(pts)
        resid = [p[1] - (a_shrunk + b_shrunk * p[0]) for p in pts]
        s_res = max(math.sqrt(sum(r * r for r in resid) / len(resid)), 0.15)
        med = clamp_pct(inv_logit_pct(a_shrunk + b_shrunk * x_target))
        spread = math.sqrt(rw * rw + s_res * s_res) * 0.85
        # Low-signal: the fit is fitting the rounding floor, not a trend.
        if max(p[2] for p in pts) < 0.10:
            med = max(med, 0.10)
            spread = max(spread, 0.8)
        rows.append({"id": tid, "q": quantiles_from(med, spread)})
    return {"trophies": rows}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(in_dir)):
        if not name.endswith(".in"):
            continue
        with open(os.path.join(in_dir, name), "r", encoding="utf-8") as f:
            case = json.load(f)
        forecast = forecast_case(case)
        out_name = name[:-3] + ".out"
        with open(os.path.join(out_dir, out_name), "w", encoding="utf-8") as f:
            f.write(json.dumps(forecast))


if __name__ == "__main__":
    main()
