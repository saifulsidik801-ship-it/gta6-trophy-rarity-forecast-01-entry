# gta6-trophy-rarity-forecast-01-entry

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/saifulsidik801-ship-it/gta6-trophy-rarity-forecast-01-entry/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/saifulsidik801-ship-it/gta6-trophy-rarity-forecast-01-entry/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Refresh-aware trophy rarity forecaster: it forecasts, for each of the 55 GTA VI trophies, the share of Exophase-tracked players who will have earned it at the case's target time, as 5/25/50/75/95% quantiles.

The model treats the counts as earners over players and learns the refresh dynamics from the case's own history. Exophase refreshes a game's counts on its own schedule: between refreshes the page is frozen, and at a refresh a bulk of newly tracked players appears. Every new player holds the universal trophies, and the cohort earns a small number of further trophies, concentrated on the early and most-earned ones. The program detects refreshes in the history, fits the new-earner profile (an exponent over the old earners), the extra earners per refresh, the players multiplier and the refresh interval, then simulates the future refresh by refresh to the target under a weighted grid of scenarios (profile shape, multiplier, extra-earner total, refresh count) and reports the weighted quantiles. When the history shows no refresh at all, it falls back to a prior centred on the launch-night refresh the competition's own rules document: players 638 to 3,868 and 103 further trophies earned beyond the universal one. The extra-earner total is a count, not a rate, so it never scales with the multiplier, and the forecast band reaches below 0.01% so far-future dilution stays covered.

## Run it

```sh
MAKEFUN_INPUT_DIR=/input MAKEFUN_OUTPUT_DIR=/output python3 main.py
```

Reads every `*.in` case in the input directory and writes one `*.out` per case (`{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}]}`). Standard library only, no network, deterministic: two runs on the same input are byte-identical.

---

<sub>Entered on [make.fun](https://make.fun/?ref=mxhczr02&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
