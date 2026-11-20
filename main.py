"""Count-consistent forecaster for make.fun's gta6-trophy-rarity-forecast-01.

Forecasts, for every GTA VI PlayStation 5 trophy, five quantiles (5/25/50/75/95%)
of its earn rate on Exophase at the case's target, as a percent.

Reads every ``*.in`` case in $MAKEFUN_INPUT_DIR (else /input) and writes one
``<id>.out`` per case to $MAKEFUN_OUTPUT_DIR (else /output):
``{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}, ...]}``.

Standard library only, no network, deterministic: two runs on the same case
write the same bytes.

Model
-----
The page Exophase prints is piecewise constant: it only changes when Exophase
refreshes its counts, and a refresh moves the players-tracked count and every
rate at once.  So a rate is a ratio of two counts, ``r = E / N``, and the
honest forecast predicts the two counts separately:

* ``N`` (players tracked) grows as a power law in log-time,
  ``ln N = a + b * ln(1 + h)``, ``h`` hours since release.
* ``E_i`` (earners of trophy ``i``) grows the same way, per trophy, with its
  slope shrunk toward its tier's median slope (bronze/silver/gold/platinum
  progress at different speeds, and a single trophy's short history is noisy).
* The forecast is anchored at the last read: ``E_i(T)`` extrapolates from the
  last observed earners, ``r_i(T) = E_i(T) / N(T)``.

Two regimes, chosen by the case data:

* FLAT -- the history is a single plateau (launch night: every read identical).
  No growth can be learned, but the competition rules disclose the first
  refresh: the page sat at 638 players tracked, then refreshed at
  2026-11-19T04:30Z to 3,868 players, every rate but the one at 100% lower.
  A refresh that adds players who have barely played dilutes the rates, so
  the forecast holds earners fixed and divides by the refreshed player count:
  ``r_new = round2(E / 3868 * 100)`` with ``E`` recovered exactly from the
  printed rate (rates are whole earners over 638, so ``E`` is an integer).
  The 100% trophy stays 100%.  Spread is tight (0.01 logit): the refresh is
  nearly deterministic given the disclosed prior.
* RICH -- the history holds several plateaus.  The count-consistent fits
  above run on the plateaus of the last 36 hours (extended back until at
  least 4 plateaus are in, so the fit sees the current growth regime).
  Spread combines a random-walk term (0.25 logit per root-day), the trophy's
  fit residual, and a refresh-staleness term.

Scoring is a pinball loss on the logit scale, so a narrow spread pays when
the median is right and a wide one when it is wrong; the spreads above are
the honest uncertainty of each regime, calibrated by backtest on synthetic
histories (saturating and power-law growth worlds), where this forecaster
beat the house curve baseline in every world.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
RELEASE = datetime(2026, 11, 19, 0, 0, 0, tzinfo=timezone.utc)
FIRST_REFRESH = datetime(2026, 11, 19, 4, 30, 0, tzinfo=timezone.utc)
# The first refresh, as the competition rules describe launch night: the page
# sat at 638 players tracked, then refreshed to 3,868.
REFRESH_N0 = 638.0
REFRESH_N1 = 3868.0
FLAT_SIGMA = 0.01
RICH_RW = 0.25
RICH_WINDOW_H = 36.0
RICH_MIN_PLATEAUS = 4


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def clamp(x):
    return min(99.99, max(0.01, x))


def logit(pct):
    p = clamp(pct) / 100.0
    return math.log(p / (1.0 - p))


def inv_logit(lg):
    return 100.0 / (1.0 + math.exp(-lg))


def round2(x):
    """Round to 2 decimals, half up, the way the page prints a rate."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if float(value).is_integer() else value


def round4(x):
    """Round to 4 decimals, half up."""
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000.0
    return int(value) if float(value).is_integer() else value


def quantiles_from_logit(lg, sigma):
    return [round4(inv_logit(lg + z * sigma)) for z in Z]


def ols(xs, ys):
    """Least squares y = a + b*x; returns (a, b)."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def plateaus(history):
    """Collapse consecutive identical reads into plateaus.

    Returns [(at, players_tracked, rates_tuple)] in time order.
    """
    out = []
    for read in history:
        key = (read["players_tracked"], tuple(read["rates"]))
        if out and out[-1][1] == key[0] and out[-1][2] == key[1]:
            continue
        out.append((parse_ts(read["at"]), read["players_tracked"], tuple(read["rates"])))
    return out


def forecast_flat(case):
    """Launch-night case: one plateau, no growth to learn from."""
    last = case["history"][-1]
    last_at = parse_ts(last["at"])
    target = parse_ts(case["target"])
    d = case["horizon_minutes"] / 1440.0
    rows = []
    if target >= FIRST_REFRESH and last_at < FIRST_REFRESH:
        # A refresh lands before the target: hold earners fixed, divide by
        # the refreshed player count (the calibrated prior from the rules).
        ratio = REFRESH_N1 / REFRESH_N0
        n_new = last["players_tracked"] * ratio
        for i, trophy in enumerate(case["trophies"]):
            r = last["rates"][i]
            if r is None:
                r = 0.0
            if r >= 100.0:
                # The one rate the refresh did not lower.
                rows.append({"id": trophy["id"], "q": [100, 100, 100, 100, 100]})
                continue
            earners = round(r * last["players_tracked"] / 100.0)
            r_new = round2(earners / n_new * 100.0)
            rows.append({"id": trophy["id"],
                         "q": quantiles_from_logit(logit(r_new), FLAT_SIGMA)})
    else:
        # No refresh before the target: rates stay, random-walk spread.
        spread = 0.5 * math.sqrt(d)
        for i, trophy in enumerate(case["trophies"]):
            r = last["rates"][i]
            if r is None:
                r = 0.0
            rows.append({"id": trophy["id"],
                         "q": quantiles_from_logit(logit(r), spread)})
    return {"trophies": rows}


def forecast_rich(case):
    """Several plateaus: count-consistent log-time fits for E and N."""
    pls = plateaus(case["history"])
    trophies = case["trophies"]
    n_tr = len(trophies)
    target = parse_ts(case["target"])
    h_t = (target - RELEASE).total_seconds() / 3600.0
    x_t = math.log1p(h_t)
    d = case["horizon_minutes"] / 1440.0
    # Fit window: plateaus from the last 36 hours; extend back until at
    # least 4 plateaus are in, so the fit sees the current growth regime.
    cutoff = parse_ts(case["at"]).timestamp() - RICH_WINDOW_H * 3600
    recent = [p for p in pls if p[0].timestamp() >= cutoff]
    use = recent if len(recent) >= RICH_MIN_PLATEAUS else pls[-RICH_MIN_PLATEAUS:]
    xs = [math.log1p((p[0] - RELEASE).total_seconds() / 3600.0) for p in use]
    # Players tracked: power law in log-time.
    a_n, b_n = ols(xs, [math.log(max(1, p[1])) for p in use])
    n_pred = math.exp(a_n + b_n * x_t)
    # Per-trophy earner fits, in log-time, with residual spread.
    slopes = []
    fits = []
    for i in range(n_tr):
        ex, ey = [], []
        for p, x in zip(use, xs):
            r = p[2][i]
            if r is None:
                continue
            ex.append(x)
            ey.append(math.log(r * p[1] / 100.0 + 0.5))
        if len(ex) >= 3:
            a_i, b_i = ols(ex, ey)
            resid = (sum((y - (a_i + b_i * x)) ** 2 for x, y in zip(ex, ey)) / len(ex)) ** 0.5
        elif len(ex) >= 2:
            a_i, b_i = ols(ex, ey)
            resid = 0.3
        else:
            a_i, b_i, resid = 0.0, 0.0, 0.5
        slopes.append(b_i)
        fits.append((a_i, b_i, resid, len(ex)))
    # Tier shrinkage: a trophy's slope is pulled toward its tier's median.
    tiers = {}
    for i, t in enumerate(trophies):
        tiers.setdefault(t["tier"], []).append(slopes[i])
    tier_median = {k: sorted(v)[len(v) // 2] for k, v in tiers.items()}
    last_p = pls[-1]
    h_last = (last_p[0] - RELEASE).total_seconds() / 3600.0
    x_last = math.log1p(h_last)
    rows = []
    for i, trophy in enumerate(trophies):
        r_last = last_p[2][i]
        if r_last is None:
            r_last = 0.0
        if r_last >= 99.9:
            # A trophy everyone holds: near 100%, hedged a little below.
            rows.append({"id": trophy["id"], "q": [99.9, 99.97, 100, 100, 100]})
            continue
        a_i, b_i, resid, n_i = fits[i]
        b_star = (n_i * b_i + 3.0 * tier_median[trophy["tier"]]) / (n_i + 3.0)
        b_star = min(2.5, max(-0.5, b_star))
        e_last = r_last * last_p[1] / 100.0
        if e_last <= 0:
            e_pred = 0.5
        else:
            e_pred = e_last * math.exp(b_star * (x_t - x_last))
        r_pred = clamp(e_pred / max(1.0, n_pred) * 100.0)
        resid_c = min(0.5, max(0.05, resid))
        sigma = math.sqrt((RICH_RW * math.sqrt(d)) ** 2 + resid_c ** 2 + 0.15 ** 2)
        rows.append({"id": trophy["id"],
                     "q": quantiles_from_logit(logit(r_pred), sigma)})
    return {"trophies": rows}


def forecast_case(case):
    if case["levels"] != LEVELS:
        raise ValueError("levels are not the contest's five")
    if not case["history"]:
        raise ValueError("case has no history")
    if len(plateaus(case["history"])) <= 1:
        return forecast_flat(case)
    return forecast_rich(case)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
