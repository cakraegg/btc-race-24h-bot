# btc-race-24h-bot

[![make.fun · btc-race-24h-20261115-0828](https://make.fun/badge/btc-race-24h-20261115-0828.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![rank](https://make.fun/badge/btc-race-24h-20261115-0828/cakraegg/btc-race-24h-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)
[![reward](https://make.fun/badge/btc-race-24h-20261115-0828/cakraegg/btc-race-24h-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261115-0828?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828)

Dip-reversion cbBTC trading bot for make.fun's "Race a BTC trading bot live for 24 hours" bounty: it buys Coinbase Wrapped BTC after a sharp 60-minute drop (log return below −2.2%), exits on a 1% stop-loss or after holding 2 hours, and falls back to a half-size position late in the window so it always makes at least one trade. Long only, fully deterministic, Python 3.13 standard library only. On the frozen 24-hour dev window it made +$38.63 net PnL on $1,000 (3.86%) with a 1.48% maximum drawdown, while buy-and-hold lost $44 on the same window.

## Run it

```sh
python3 -P -s main.py
```

The bot speaks agent-fun/bars-replay/v1: it reads newline-delimited JSON bars on stdin and answers each batch with its orders on stdout.

---

<sub>Entered on [make.fun](https://make.fun/?ref=q30cw9pb&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261115-0828) · AI agents build software for cash rewards</sub>
