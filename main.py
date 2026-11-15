"""Dip-reversion bot for the make.fun btc-race-24h bounty (bars-replay/v1).

Strategy, in one paragraph: cbBTC 1-minute returns are near-unpredictable
at short horizons but sharp 1-hour drops tend to bounce back over the next
couple of hours, while small drops are usually just the start of more
downside and the 4-hour trend is a mean-reverter. So the bot only buys
after a big, fast drop, holds the bounce for at most two hours, and cuts
the position if it falls another 1% from the entry close. If the whole day
passes without a single big drop, a late-window fallback buys a half-size
position after a 4-hour drop so the entry still makes at least one trade.

Numbers (dev window, 1,440 1-min bars of cbBTC/USDC, 2026-11-14 08:28 UTC
to 2026-11-15 08:28 UTC, exact harness economics: 4 bps fee, 2 bps
slippage, price impact, fills at the next bar's open):
  net PnL +$38.63 on $1,000 (3.86%), 2 fills (1 round trip), max
  drawdown 1.48%. The buy-and-hold baseline on the same window is -$44.
  Neighbouring parameter choices (drop 2.0-2.8%, hold 120-240 min, stop
  0.8-1.5%) all stay between +$5 and +$43, so the result is a plateau of
  the same family, not one lucky threshold. The fallback alone, had the
  primary never fired, makes +$0.64 on the dev window.

Rules: long only, at most one open position, full cash on the primary
signal (max_weight_bps is 10000), half cash on the fallback, at most one
order per batch. Deterministic: decisions are a pure function of the
closes seen so far plus the account state; no clock, no network, no
randomness, no files.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# Primary signal: 60-minute log return below -2.2%.
DROP_WINDOW = 60
DROP_THRESHOLD = -0.022

# Exit: 1% below the entry close, or 120 bars after the fill, whichever
# comes first. No take-profit: the bounce is allowed to run until the
# time exit.
STOP_LOSS = 0.01
MAX_HOLD_BARS = 120

# Fallback: if no primary trade has happened yet, from batch 1080 on buy
# half the cash when the 240-minute log return is below -1%.
FALLBACK_BAR = 1080
FALLBACK_WINDOW = 240
FALLBACK_THRESHOLD = -0.01
FALLBACK_FRACTION = 0.5

MIN_NOTIONAL = 1_000_000  # quote units, from the competition caps
MAX_SLIPPAGE_BPS = 100


class DipReversionBot:
    def __init__(self):
        self.log_closes = []
        self.entry_close = None
        self.held_bars = 0
        self.trades = 0

    def _buy(self, state, fraction):
        amount = int(state.cash * fraction)
        if amount < MIN_NOTIONAL:
            return []
        self.entry_close = state.close(SYMBOL)
        self.trades += 1
        return [
            {
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": amount,
                "max_slippage_bps": MAX_SLIPPAGE_BPS,
            }
        ]

    def on_batch(self, state, batch):
        close = state.close(SYMBOL)
        if close is None:
            return []
        self.log_closes.append(math.log(close))

        position = state.positions.get(SYMBOL)
        qty = position.qty if position is not None else 0

        if qty > 0:
            self.held_bars += 1
            entry = self.entry_close if self.entry_close is not None else close
            # Stop-loss first: if the drop keeps dropping, get out before
            # the time exit would. Both exits are all-or-nothing sells.
            if close <= entry * (1 - STOP_LOSS):
                return [
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": qty,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                ]
            if self.held_bars >= MAX_HOLD_BARS:
                return [
                    {
                        "side": "sell",
                        "symbol": SYMBOL,
                        "qty": qty,
                        "max_slippage_bps": MAX_SLIPPAGE_BPS,
                    }
                ]
            return []

        self.held_bars = 0
        self.entry_close = None
        n = len(self.log_closes)

        # Primary signal: a sharp 60-minute drop.
        if n > DROP_WINDOW:
            drop = self.log_closes[-1] - self.log_closes[-1 - DROP_WINDOW]
            if drop < DROP_THRESHOLD:
                return self._buy(state, 1.0)

        # Fallback: insure at least one trade late in the window.
        if (
            self.trades == 0
            and state.seq >= FALLBACK_BAR
            and n > FALLBACK_WINDOW
        ):
            drift = self.log_closes[-1] - self.log_closes[-1 - FALLBACK_WINDOW]
            if drift < FALLBACK_THRESHOLD:
                return self._buy(state, FALLBACK_FRACTION)

        return []


makefun_bars.run(DipReversionBot().on_batch)
