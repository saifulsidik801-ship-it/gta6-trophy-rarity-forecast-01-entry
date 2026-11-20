# gta6-trophy-rarity-forecast-01-entry

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/saifulsidik801-ship-it/gta6-trophy-rarity-forecast-01-entry/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/saifulsidik801-ship-it/gta6-trophy-rarity-forecast-01-entry/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A count-consistent forecaster for GTA VI's PlayStation 5 trophies on Exophase: two days after launch, it predicts each trophy's earn rate a week after launch (2026-11-26 00:00 UTC) as five quantiles (5/25/50/75/95%), scored by pinball loss on the logit scale.

The model treats every earn rate as a ratio of two counts, `r = E / N` (earners over players tracked), and forecasts the two counts separately as power laws in log-time since release, with each trophy's growth slope shrunk toward its tier's median. On launch night, when the history is a single flat plateau, it predicts the first Exophase refresh with the calibrated prior from the competition rules (players 638 → 3,868, earners held fixed — pure dilution). See `main.py` for the full model and the backtest notes.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Standard library only, no network, deterministic. Reads every `*.in` case in the input directory and writes one `<id>.out` per case.

---

<sub>Entered on [make.fun](https://make.fun/?ref=mxhczr02&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
