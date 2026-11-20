# STUDY-V5 — gta6-trophy-rarity-forecast-01

Builder: v5 (fresh re-type from the FINAL-WAY-ANALYSIS.md §4 spec; v3/v4
entry code never read).
Date: 2026-11-20. Competition closes 2026-11-21 18:30 WIB (pot $250).
Targets: v3 counting loss 0.0784 (#99); top 1 practice 0.000046
(argaromit, observed data — unrecoverable, NOT chased). 6,901 entries.

## (a) The point of v5: the final, not the practice

The practice top-1 (0.000046) was observed data, not a model: the top
entries read the live Exophase page while it showed N=3,868 and hardcoded
the exact 04:30 rates. That window closed ~Nov 20 07:19 UTC and the data
is unrecoverable (Wayback: zero snapshots; archive.today: 404; the live
page has moved on to N=10,000). No rebuild can chase practice top-1.
The FINAL (Nov 26 target, pays the $250) is a separate game: a 4.5-day
extrapolation, winning loss most likely ~0.3–0.8. v5 is built for it.

## (b) The method (FINAL-WAY-ANALYSIS.md §4, implemented exactly)

1. Collapse the history to distinct refresh states (drop consecutive
   identical reads).
2. DROP the launch-night flat state (N=638) and any state before the
   first refresh — a different (reviewer) population that poisons the
   fit (proven: v4 with all states scores 2.93; excluding launch 0.47–0.50).
3. Per trophy, over the LAST 3 distinct states: least-squares fit
   logit(rate) = a + b·ln(1+t), t = hours since 2026-11-19T00:00Z,
   0.5-count continuity correction rate_adj = (E+0.5)/(N+1)·100.
   Fewer than 3 distinct states → persistence + random-walk spread.
4. Shrink the slope: beta = median b over trophies with max rate ≥ 1%
   in the used states; b ← 0.5·b + 0.5·beta; re-centre
   a = mean(logit − b·x).
5. Median: the shrunk line read at the case target (read from the input
   case's target timestamp, not hardcoded).
6. Spread: s = sqrt((0.5·sqrt(d))² + s_res²) × 0.85, d = horizon in days,
   s_res = residual SD of the shrunk fit (floor 0.15).
   q_τ = inv_logit(logit(med) + z_τ·s), z = (−1.645, −0.674, 0, 0.674, 1.645).
7. Low-signal: max rate across the used states < 0.10% → median floored
   at 0.10%, spread floored at 0.8.
8. Trophy #2 (100%): all quantiles 100. Clamp everything to [0.01, 99.99].

Why last-3 + shrinkage (analysis §3c): last-2 collapses under noise
(0.26 → 3.54 at noise sd 0.30); last-3 with 50% slope shrinkage is the
robustness win (overall 0.372 vs 0.410 for the unshrunk house-curve form);
a slightly narrower spread (×0.85) helps once the median is stabilised.

## (c) Local validation (scorer replica, RULES worked example exact)

- RULES worked example: 0.403404 exact.
- Practice (p00/p01): v5 falls back to persistence + RW spread, BY
  DESIGN — after dropping the flat state there are 0 distinct states
  left (the whole practice history is the flat page). Practice loss vs
  the alpha-0.6 candidate truth (Nov-20 live counts as weights):
  1.5112 (v4 study: 1.5118). Output is byte-identical to an
  independently computed house-persistence baseline. The practice is
  not the target; v5 does not try to win it.
- Synthetic final-regime case (real data: flat launch state + 04:30
  alpha-1.0 state + Nov 20 10:33 live rates N=10,000 + a Nov 21 07:00
  state, target Nov 26 00:00Z): trend path taken, format valid,
  deterministic. Top medians: #20 Beat Cal 41.61%, #3 Ch1 34.58%,
  #8 19.22%, #21 5.79%, #35 3.91%, #4 3.43%, #46 3.00%; #2 stays 100%;
  platinum #1 0.02% (its recent states are all 0.00% — a known miss,
  analysis §5: the model under-predicts the rarest trophies).
- Low-signal floor micro-test: a trophy stuck at 0.02% in all 3 used
  states → median floored at 0.10% (PASS); spread is max(computed, 0.8).
- Format: 55 rows, ids 1–55 once, non-decreasing, 0–100, 3,077 B
  (cap 65,536). Deterministic (two runs byte-identical). Runtime 0.04 s.
- main.py takes its final content from 2 write/edit messages in this
  session (full write, then a robustness edit to the last-rates lookup).

## (d) Honest expected final loss

In-simulator (analysis §6): recommended model ~0.35 overall (0.26 at
zero noise, ~0.49 at high noise); house-curve form ~0.41; v4 as built
~2.9 (launch-state poison); v4 with launch removed ~0.50.
Real world (weekend surge, refresh lumpiness, possible patch, N-growth
surprises): ~0.5–0.8 for v5, ~0.6–1.0 for the house curve baseline.
The edge over the house bar is real but thin (~15% in-sim, ~30% at
high noise), and the superbot house model is an unknown wildcard.
This will NOT be near the practice top-1's 0.000046 — that was
observed data. The final is a genuinely hard 4.5-day extrapolation.

Caveats:
- My synthetic-f00 loss (0.43 vs persistence 0.15) is NOT evidence
  about the real final: the synthetic "truth" was built by continuing
  the last log-step only half a step, so it sits almost on top of the
  last state and flatters persistence. The analysis's population
  simulator is the real accuracy validation (trend ~0.35 vs
  persistence ~2.18 in-sim).
- If the real f00 history has only 2 distinct states in the last 24h,
  the last-3 window reaches back to the 04:30 refresh (a population
  change, not a trend) and the fit degrades (analysis §7). The spec
  has no guard for this; the program follows the spec.
- A trophy whose recent states are all 0.00% (e.g. platinum) can get
  a very low fitted median (0.02% here) when its 04:30 rate is ≥ 0.10%,
  so the low-signal floor does not trigger. Known miss, analysis §5.

## Verification log
- [x] RULES worked example: 0.403404 exact.
- [x] Practice: persistence fallback, loss 1.5112 vs alpha-0.6 truth,
      byte-identical to independent house baseline.
- [x] Synthetic final regime: trend path, sane medians, format valid.
- [x] Low-signal floor micro-test: median 0.10 PASS.
- [x] Deterministic (2 identical runs), runtime 0.04 s, chmod +x,
      output <= 65,536 B, format valid.
- [x] main.py from 2 write/edit messages in this session.
- [ ] Commit + push; tree clean.
