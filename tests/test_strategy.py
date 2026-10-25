from decimal import Decimal

import pytest

from sollab.strategy import (
    ALREADY_LONG,
    ALREADY_SHORT,
    BLOCKED_BY_OPEN_POSITION,
    INSUFFICIENT_HISTORY,
    NO_CROSSOVER,
    OpenView,
    StrategyParams,
    assess,
    evaluate,
)


def _params(**overrides) -> StrategyParams:
    values = {
        "fast_window": 2,
        "slow_window": 3,
        "slippage_bps": Decimal("0"),
        "symbols": ("BTC",),
    }
    values.update(overrides)
    return StrategyParams(**values)


def test_insufficient_history_and_flat_series():
    params = _params()
    short = [Decimal(10)] * 3
    decision = assess(short, params, None, "BTC")
    assert decision.rejection_reason == INSUFFICIENT_HISTORY
    assert decision.action == "reject"

    flat = [Decimal(10)] * 4
    decision = assess(flat, params, None, "BTC")
    assert decision.signal == "none"
    assert decision.rejection_reason == NO_CROSSOVER


def test_bullish_and_bearish_crossovers():
    params = _params()
    bullish = assess([Decimal(x) for x in (10, 10, 10, 14)], params, None, "BTC")
    assert bullish.signal == "bullish_crossover"
    assert bullish.action == "open_long"
    assert bullish.rejection_reason is None

    bearish = assess([Decimal(x) for x in (10, 10, 10, 6)], params, None, "BTC")
    assert bearish.signal == "bearish_crossover"
    assert bearish.action == "open_short"


def test_position_rules_do_not_reverse_same_bar():
    params = _params()
    bullish = evaluate([Decimal(x) for x in (10, 10, 10, 14)], 2, 3)
    bearish = evaluate([Decimal(x) for x in (10, 10, 10, 6)], 2, 3)

    held_long = decide_view(bullish, OpenView("BTC", "long"), "BTC")
    assert held_long.rejection_reason == ALREADY_LONG

    held_short = decide_view(bearish, OpenView("BTC", "short"), "BTC")
    assert held_short.rejection_reason == ALREADY_SHORT

    close_long = decide_view(bearish, OpenView("BTC", "long"), "BTC")
    assert close_long.action == "close_long"
    assert close_long.note == "reversal_not_taken_same_bar"
    assert close_long.rejection_reason is None

    close_short = decide_view(bullish, OpenView("BTC", "short"), "BTC")
    assert close_short.action == "close_short"
    assert close_short.note == "reversal_not_taken_same_bar"

    blocked = decide_view(bullish, OpenView("SOL", "short"), "BTC")
    assert blocked.rejection_reason == BLOCKED_BY_OPEN_POSITION


def decide_view(signal, position, symbol):
    from sollab.strategy import decide

    return decide(signal, position, symbol)


def test_signal_uses_only_closes_up_to_the_bar():
    params = _params()
    prefix = [Decimal(x) for x in (10, 10, 10, 14)]
    with_future = prefix + [Decimal(1)]
    assert assess(prefix, params, None, "BTC").signal == "bullish_crossover"
    # The future close is invisible when the series stops at the crossover bar.
    assert assess(with_future, params, None, "BTC").signal != "bullish_crossover"


def test_invalid_windows_rejected():
    with pytest.raises(ValueError):
        StrategyParams(fast_window=5, slow_window=5)
    with pytest.raises(ValueError):
        evaluate([Decimal(1), Decimal(2)], fast_window=2, slow_window=2)
