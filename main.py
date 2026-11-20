#!/usr/bin/env python3
"""Forecast GTA VI trophy earn rates on Exophase at a case's target.

Model (earners vs players, refresh-aware, scenario mixture):
  Exophase refreshes a game's counts on its own schedule: between refreshes
  the page is frozen, and at a refresh a bulk of newly tracked players
  appears. Every new player holds the universal trophies (the ones at 100%),
  and the cohort earns a small number of further trophies, concentrated on
  the early / most-earned ones. Existing players also add trophies at each
  refresh. So a trophy's rate moves as earners / players, and both sides
  jump at refreshes.

  The program learns the refresh dynamics from the case's own history:
  it detects refreshes (players-tracked jumps / rate changes), fits the
  new-earner profile (an exponent alpha over the old earners), the extra
  earners per new player, the players multiplier per refresh and the
  refresh interval. It then simulates the future refresh by refresh to the
  target under a weighted grid of scenarios (alpha, multiplier, refresh
  count, extra rate) and reports the weighted quantiles of the simulated
  target rates. When the history shows no refresh at all (flat launch
  night), it falls back to a prior: a refresh is coming, the new cohort is
  several times the tracked players, and its extra trophies concentrate on
  the most-earned ones.

  Standard library only, no network, deterministic.
"""

import json
import math
import os
import sys

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)


def clamp_pct(x):
    # The scorer clamps the ACTUAL rate to [0.01, 99.99] before the logit,
    # but a forecast quantile may be any finite value in [0, 100]: a true
    # rate can fall below 0.01 after many refreshes, and the band can only
    # cover it if its lower edge is allowed down there too. The floor of
    # 0.001 keeps every quantile finite and ordered while reaching the
    # far tail; in the usual regime (rates >= 0.1) it changes nothing.
    if x < 0.001:
        return 0.001
    if x > 99.99:
        return 99.99
    return x


def parse_time(s):
    """ISO 8601 UTC -> epoch seconds (no datetime import games, plain math)."""
    # '2026-11-19T03:00:00Z' (fractional seconds tolerated)
    date, clock = s.split("T")
    y, mo, d = (int(v) for v in date.split("-"))
    clock = clock.rstrip("Z")
    if "." in clock:
        clock = clock.split(".")[0]
    h, mi, sec = (int(v) for v in clock.split(":"))
    days = _days_since_epoch(y, mo, d)
    return days * 86400 + h * 3600 + mi * 60 + sec


def _days_since_epoch(y, mo, d):
    days = 0
    for yy in range(1970, y):
        days += 366 if (yy % 4 == 0 and (yy % 100 != 0 or yy % 400 == 0)) else 365
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
             31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for mm in range(1, mo):
        days += mdays[mm - 1]
    return days + (d - 1)


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return 0.5 * (s[n // 2 - 1] + s[n // 2])


def weighted_quantile(pairs, level):
    """pairs: list of (value, weight). Return the level quantile."""
    tot = sum(w for _, w in pairs)
    if tot <= 0:
        return pairs[0][0] if pairs else 0.0
    ordered = sorted(pairs, key=lambda p: p[0])
    acc = 0.0
    prev_v, prev_c = ordered[0][0], 0.0
    for v, w in ordered:
        acc += w / tot
        if acc >= level:
            if acc == level or v == prev_v:
                return v
            # linear interpolation inside this step
            frac = (level - prev_c) / max(acc - prev_c, 1e-12)
            return prev_v + frac * (v - prev_v)
        prev_v, prev_c = v, acc
    return ordered[-1][0]


def detect_refreshes(history, trophies_n):
    """Return list of refresh events: dicts with dt, p_before, p_after,
    earn_before (list), earn_after (list). A refresh is a read whose
    players_tracked or any rate differs from the previous read."""
    events = []
    prev = None
    for read in history:
        rates = read.get("rates") or []
        players = read.get("players_tracked") or 0
        earn = []
        for i in range(trophies_n):
            r = rates[i] if i < len(rates) else None
            earn.append(None if r is None else r * players / 100.0)
        if prev is not None:
            changed = players != prev["players"]
            if not changed:
                for a, b in zip(earn, prev["earn"]):
                    if a is None or b is None:
                        continue
                    if abs(a - b) > 0.51:  # more than rounding noise
                        changed = True
                        break
            if changed:
                events.append({
                    "dt": parse_time(read["at"]) - parse_time(prev["at"]),
                    "p_before": prev["players"],
                    "p_after": players,
                    "earn_before": prev["earn"],
                    "earn_after": earn,
                })
        prev = {"players": players, "earn": earn, "at": read["at"]}
    return events


def fit_alpha(events, universal, earn_last):
    """Fit the exponent alpha of the new-earner profile dE ~ E^alpha from
    observed refreshes. Returns (best_alpha, score)."""
    if not events:
        return None, None
    grid = [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0]
    best, best_err = None, None
    for alpha in grid:
        err = 0.0
        cnt = 0
        for ev in events:
            d_total = 0.0
            wsum = 0.0
            weights = []
            for i, e in enumerate(ev["earn_before"]):
                if universal[i] or e is None:
                    weights.append(0.0)
                    continue
                w = (max(e, 0.0) ** alpha) if alpha > 0 else 1.0
                weights.append(w)
                wsum += w
            for i, e in enumerate(ev["earn_before"]):
                if universal[i] or e is None:
                    continue
                obs = (ev["earn_after"][i] or 0.0) - e
                d_total += max(obs, 0.0)
            if wsum <= 0 or d_total <= 0:
                continue
            for i, e in enumerate(ev["earn_before"]):
                if universal[i] or e is None:
                    continue
                obs = max((ev["earn_after"][i] or 0.0) - e, 0.0)
                pred = d_total * weights[i] / wsum
                # squared error on a log-ish scale, robust to zeros
                err += (math.log1p(pred) - math.log1p(obs)) ** 2
                cnt += 1
        if cnt:
            err /= cnt
            if best_err is None or err < best_err:
                best_err, best = err, alpha
    return best, best_err


def forecast_case(case):
    trophies = case["trophies"]
    n = len(trophies)
    history = case["history"]
    horizon_min = float(case.get("horizon_minutes") or 0)
    last = history[-1]
    p_last = float(last.get("players_tracked") or 0)
    rates_last = last.get("rates") or []
    earn_last = []
    for i in range(n):
        r = rates_last[i] if i < len(rates_last) else None
        earn_last.append(0.0 if r is None else r * p_last / 100.0)
    universal = []
    for i in range(n):
        r = rates_last[i] if i < len(rates_last) else None
        universal.append(bool(r is not None and r >= 99.99))

    events = detect_refreshes(history, n)

    # --- fitted dynamics (or prior when the history is flat) ---
    # Shapes: ("pow", alpha) spreads the extra earners ~ E^alpha, while
    # ("top", k) gives them only to the k most-earned trophies. Totals are
    # counts of extra non-universal earners per refresh, NOT rates: the
    # documented launch refresh added a fixed 103 of them whatever the
    # player multiplier, so total and multiplier must not be coupled.
    alpha_fit, _ = fit_alpha(events, universal, earn_last)
    if events:
        # extra non-universal earners per refresh, pooled over events
        extras = []
        for ev in events:
            extra = 0.0
            for i in range(n):
                if universal[i]:
                    continue
                b = ev["earn_before"][i] or 0.0
                a = ev["earn_after"][i] or 0.0
                extra += max(a - b, 0.0)
            extras.append(extra)
        t_mid = median(extras) if extras else 100.0
        mults = []
        for ev in events:
            if ev["p_before"] > 0 and ev["p_after"] > ev["p_before"]:
                mults.append(ev["p_after"] / ev["p_before"])
        m_mid = median(mults) if mults else 2.0
        dts = [ev["dt"] for ev in events if ev["dt"] > 0]
        interval_h = (median(dts) / 3600.0) if dts else 5.0
        near = _neighbour_grid(alpha_fit, [0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0])
        shape_pairs = [(("pow", a), 0.6 if a == alpha_fit else 0.1)
                       for a in near]
        shape_pairs += [(("top", 12), 0.1), (("top", 20), 0.1)]
        m_pairs = [(max(1.05, m_mid * 0.7), 0.2), (m_mid, 0.6),
                   (m_mid * 1.4, 0.2)]
        t_pairs = [(max(10.0, t_mid * 0.7), 0.25), (t_mid, 0.5),
                   (t_mid * 1.4, 0.25)]
    else:
        # flat history: prior from the launch-night refresh pattern.
        # The kit's own rules document that refresh: players 638 -> 3868
        # (multiplier ~6.06) and 103 further trophies earned by the new
        # cohort beyond the universal one (4276 - 943 - 3230), so the
        # prior is centred there, not on a guess.
        shape_pairs = [(("pow", 1.0), 0.05), (("pow", 2.0), 0.15),
                       (("pow", 4.0), 0.20), (("pow", 6.0), 0.10),
                       (("top", 12), 0.30), (("top", 20), 0.20)]
        m_pairs = [(4.0, 0.2), (6.0, 0.6), (9.0, 0.2)]
        t_pairs = [(70.0, 0.25), (103.0, 0.5), (140.0, 0.25)]
        interval_h = 4.5
        m_mid = 6.0
        t_mid = 103.0

    # --- scenario grid ---
    # refresh counts: expected count from horizon / interval, +-1
    exp_n = horizon_min / 60.0 / interval_h if interval_h > 0 else 0.0
    n_base = int(round(exp_n))
    n_counts = sorted(set([max(0, n_base - 1), n_base, n_base + 1]))
    if horizon_min <= 120:
        n_counts = sorted(set([0, 1, 2]))
    n_weights = {}
    for k in n_counts:
        if k == n_base:
            n_weights[k] = 0.6
        elif abs(k - n_base) == 1:
            n_weights[k] = 0.2
        else:
            n_weights[k] = 0.1
    if horizon_min <= 120:
        # a refresh inside 90 minutes is near-certain at launch cadence
        # (the task text says the practice straddles one); the no-refresh
        # case would put the top quantiles at the flat rates and cost far
        # more than it can ever save, so it gets no weight here
        n_weights = {0: 0.0, 1: 0.85, 2: 0.15}
        n_counts = [0, 1, 2]

    def norm(pairs):
        tot = sum(w for _, w in pairs)
        return [(v, w / tot) for v, w in pairs] if tot > 0 else pairs

    shape_pairs = norm(shape_pairs)
    m_pairs = norm(m_pairs)
    t_pairs = norm(t_pairs)

    # --- simulate ---
    # per trophy: list of (rate, weight)
    buckets = [[] for _ in range(n)]
    for shape, w_s in shape_pairs:
        for mult, w_m in m_pairs:
            for total_extra, w_t in t_pairs:
                for k, w_n in ((kk, n_weights[kk]) for kk in n_counts):
                    w = w_s * w_m * w_t * w_n
                    if w <= 0:
                        continue
                    rates = _simulate(earn_last, p_last, universal, shape,
                                      mult, total_extra, k)
                    for i in range(n):
                        buckets[i].append((rates[i], w))

    out = []
    for i in range(n):
        qs = []
        for lv in LEVELS:
            v = weighted_quantile(buckets[i], lv)
            qs.append(round(clamp_pct(v), 4))
        # enforce non-decreasing after rounding
        for j in range(1, 5):
            if qs[j] < qs[j - 1]:
                qs[j] = qs[j - 1]
        out.append({"id": trophies[i]["id"], "q": qs})
    return {"trophies": out}


def _neighbour_grid(center, grid):
    if center is None:
        return grid
    near = sorted(grid, key=lambda g: abs(g - center))[:3]
    return sorted(set(near + [center]))


def _simulate(earn, players, universal, shape, mult, total_extra, n_refresh):
    """Simulate n_refresh refreshes to the target. Returns rates in percent.
    shape is ("pow", alpha): extra earners ~ E^alpha, or ("top", k): extra
    earners ~ E within the k most-earned trophies only. total_extra is the
    number of extra non-universal earners the FIRST refresh brings; later
    refreshes bring 0.85x as many. The total is a parameter, NOT a rate:
    a refresh that adds many players adds the same documented number of
    further trophies, so the total must not scale with the multiplier."""
    earn = list(earn)
    p = float(players)
    n = len(earn)
    decay = 0.85
    for step in range(n_refresh):
        m = 1.0 + (mult - 1.0) * (decay ** step)
        p_new = p * m
        dp = p_new - p
        if dp <= 0:
            break
        extra_total = total_extra * (decay ** step)
        kind, param = shape
        weights = []
        wsum = 0.0
        if kind == "top":
            order = sorted([i for i in range(n) if not universal[i]],
                           key=lambda i: -earn[i])
            top = set(order[:int(param)])
            for i in range(n):
                w = earn[i] if i in top else 0.0
                weights.append(w)
                wsum += w
        else:
            alpha = param
            for i in range(n):
                if universal[i]:
                    weights.append(0.0)
                    continue
                e = max(earn[i], 0.0)
                w = (e ** alpha) if alpha > 0 else 1.0
                # floor so a zero-earner trophy can still gain a little
                w += 0.05
                weights.append(w)
                wsum += w
        for i in range(n):
            if universal[i]:
                earn[i] = p_new  # every new player holds it
            elif wsum > 0:
                earn[i] += extra_total * weights[i] / wsum
            if earn[i] > p_new:
                earn[i] = p_new
        p = p_new
    rates = []
    for i in range(n):
        if universal[i]:
            rates.append(100.0)
        else:
            rates.append(earn[i] / p * 100.0 if p > 0 else 0.0)
    return rates


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(f for f in os.listdir(in_dir) if f.endswith(".in"))
    for name in names:
        with open(os.path.join(in_dir, name), "r", encoding="utf-8") as fh:
            case = json.load(fh)
        result = forecast_case(case)
        stem = name[:-3]
        with open(os.path.join(out_dir, stem + ".out"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, separators=(",", ":"))
            fh.write("\n")


if __name__ == "__main__":
    main()
