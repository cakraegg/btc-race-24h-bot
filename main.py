"""Staged dip-reversion bot for the make.fun btc-race-24h bounty
(bars-replay/v1). This is v2: it replaces the single all-in buy of v1
with two tranches that scale into a sharp drop instead of catching the
whole falling knife at once.

The idea, in one paragraph: a one-hour drop of about two percent in
cbBTC usually bounces, but the first sign of it is not the bottom --
on the dev window the price slid another percent after the first
signal before turning. So the bot only risks a quarter of its cash on
the first signal (a 60-minute log return below -2.2%), and only commits
the rest when the drop deepens to -2.8%, which on the dev window is
exactly where the bottom was. The whole position is then held for at
most two hours from the first fill, with a 1.5% stop under the
notional-weighted average entry as insurance against the drop turning
into a crash. If the day passes with no sharp drop at all, a late
fallback buys half the cash after a four-hour drift below -1%, so the
entry still trades at least once.

Dev window (1,440 1-minute bars of cbBTC/USDC, 2026-11-14 08:28 UTC to
2026-11-15 08:28 UTC; exact harness economics: 4 bps fee, 2 bps
slippage, constant-product impact, fills at the next bar's open):
  net PnL +$46.31 on $1,000 (4.63%), 3 fills (2 buys, 1 sell), max
  drawdown 0.53%. v1 on the same window made +$38.63 with a 1.47%
  drawdown, so v2 is +$7.68 better and about three times calmer.

Why this is a plateau, not a lucky threshold (grid search over the
same exact engine):
  first tranche 0.10-0.50 of cash -> +$44.35 to +$47.20, smooth;
  second threshold -2.7% or -2.8% -> +$45.70 / +$46.31;
  first threshold -2.1% or -2.2% -> +$46.31 either way;
  hold 110-130 bars -> +$40.95 to +$46.31;
  stop 1%, 1.5%, 2% or none -> +$46.31 (it never fires on dev).
  Variants that were tried and REJECTED because they lost money on
  dev: a 30-minute detection window (best +$8.88), a trailing stop or
  partial take-profit (both cut the bounce short), and RSI / Bollinger
  / bounce confirmations (they delay the entry past the bottom).
  The one genuine cliff is the second threshold: at -2.9% it never
  fires and only the first tranche trades (+$10.32). That is the
  honest trade-off of the design -- if the race window's drop is
  shallower, v2 still trades the first tranche and stays profitable,
  it just does not get the cheap second one.

Race-window risk, stated plainly: everything depends on whether the
next 24 hours contain a sharp drop with a bounce, like the dev
window's. A shallower drop (-2.2% to -2.7%) still leaves a small
profit from the first tranche; no drop at all leaves only the
fallback; a drop that keeps crashing is capped by the 1.5% stop.

Rules: long only, at most one open position, at most one order per
batch, at most one round per window. Deterministic: every decision is
a pure function of the closes seen so far and the account state; no
clock, no network, no randomness, no files.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

ASSET = "CBBTC"

# One hour of closes defines a "drop": the log return over this span.
SPAN = 60
# First tranche: a quarter of the cash on a -2.2% hourly drop.
FIRST_DIP = -0.022
FIRST_SHARE = 0.25
# Second tranche: the rest of the cash if the drop deepens to -2.8%.
SECOND_DIP = -0.028

# One round lives at most this many bars from its first fill, and is
# cut if the close falls this far under the average entry close.
HOLD_LIMIT = 120
STOP_FRAC = 0.015

# Late safety net: from this batch on, with no buy yet, a half-size
# position after a -1% drift over four hours.
LATE_BATCH = 1080
DRIFT_SPAN = 240
DRIFT_FLOOR = -0.01
LATE_SHARE = 0.5

FLOOR_NOTIONAL = 1_000_000  # quote units: the $1 minimum from the caps
SLIPPAGE_CAP = 100  # bps, from the competition caps


def make_handler():
    """Return the per-batch callback. All mutable state lives in the
    closure dict below, so nothing leaks between runs."""

    # closes: log closes seen so far, oldest first.
    # tranche: 0 = nothing bought yet, 1 = first tranche filled,
    #   2 = second tranche filled (round fully invested).
    # pending: (notional, close) of a buy order sent on the previous
    #   batch and not yet known filled; folded into the average entry
    #   once the position actually appears.
    # spent / entry_num: notional-weighted average entry close of the
    #   filled buys: entry = entry_num / spent.
    # bars_held: batches with a position open, counting from the fill.
    # buys: number of buys that actually filled (gates the fallback).
    # last_qty: position size at the previous batch, used to tell a
    #   filled buy (qty grew) from a rejected one (qty unchanged).
    # finished: the round (or the fallback) is over; trade no more.
    s = {
        "closes": [],
        "tranche": 0,
        "pending": None,
        "spent": 0,
        "entry_num": 0,
        "bars_held": 0,
        "buys": 0,
        "last_qty": 0,
        "finished": False,
    }

    def avg_entry():
        if s["spent"] <= 0:
            return None
        return s["entry_num"] / s["spent"]

    def drop_over(span):
        """Log return of the latest close over the last `span` bars."""
        hist = s["closes"]
        if len(hist) <= span:
            return None
        return hist[-1] - hist[-1 - span]

    def send_buy(state, notional):
        """Queue a buy of `notional` quote units, remembering it as
        pending so the average entry only counts it once filled."""
        if notional < FLOOR_NOTIONAL:
            return []
        s["pending"] = (notional, state.close(ASSET))
        return [
            {
                "side": "buy",
                "symbol": ASSET,
                "notional_quote_units": int(notional),
                "max_slippage_bps": SLIPPAGE_CAP,
            }
        ]

    def send_sell(state, qty):
        s["finished"] = True
        return [
            {
                "side": "sell",
                "symbol": ASSET,
                "qty": qty,
                "max_slippage_bps": SLIPPAGE_CAP,
            }
        ]

    def tick(state, batch):
        close = state.close(ASSET)
        if close is None:
            return []
        s["closes"].append(math.log(close))

        held = state.positions.get(ASSET)
        qty = held.qty if held is not None else 0

        if qty > 0:
            # A pending buy has landed only if the position grew since
            # the previous batch. A rejected buy (max slippage, weight)
            # leaves the size unchanged: drop it uncounted so the
            # average entry is never polluted and the tranche can be
            # tried again on a later batch.
            if s["pending"] is not None:
                if qty > s["last_qty"]:
                    notional, at_close = s["pending"]
                    s["entry_num"] += notional * at_close
                    s["spent"] += notional
                    s["buys"] += 1
                    s["tranche"] += 1
                s["pending"] = None
            s["last_qty"] = qty
            s["bars_held"] += 1

            entry = avg_entry()
            if entry is None:
                entry = close
            # Stop first: a drop that keeps dropping is cut before the
            # time exit would sell it.
            if close <= entry * (1 - STOP_FRAC):
                return send_sell(state, qty)
            if s["bars_held"] >= HOLD_LIMIT:
                return send_sell(state, qty)
            # Still room and still falling: scale in the second tranche.
            # Capped by the weight room so a rising mark between the
            # tranches can never trip the engine's max-weight reject.
            if s["tranche"] == 1:
                dip = drop_over(SPAN)
                if dip is not None and dip < SECOND_DIP:
                    room = state.weight_room(ASSET)
                    return send_buy(state, min(state.cash, room))
            return []

        # Flat. A pending buy that never filled was rejected: drop it
        # and let the trigger fire again on a later batch.
        s["pending"] = None
        s["bars_held"] = 0
        s["spent"] = 0
        s["entry_num"] = 0
        s["last_qty"] = 0
        if s["finished"]:
            return []

        # First tranche: a sharp hourly drop, a quarter of the cash.
        dip = drop_over(SPAN)
        if s["tranche"] == 0 and dip is not None and dip < FIRST_DIP:
            return send_buy(state, int(state.cash * FIRST_SHARE))

        # Late safety net, only when nothing ever bought.
        if s["buys"] == 0 and state.seq >= LATE_BATCH:
            drift = drop_over(DRIFT_SPAN)
            if drift is not None and drift < DRIFT_FLOOR:
                return send_buy(state, int(state.cash * LATE_SHARE))

        return []

    return tick


makefun_bars.run(make_handler())
