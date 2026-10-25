from datetime import datetime, timezone
from decimal import Decimal

from sollab.ledger import (
    INSUFFICIENT_CASH,
    NOTIONAL_EXCEEDS_LIMIT,
    POSITION_ALREADY_OPEN,
    SYMBOL_MISMATCH,
    PaperLedger,
    q,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 1, 2, tzinfo=timezone.utc)


def _ledger(**overrides) -> PaperLedger:
    values = {"slippage_bps": Decimal("0")}
    values.update(overrides)
    ledger = PaperLedger(**values)
    ledger.seed(T0)
    return ledger


def _assert_identity(ledger: PaperLedger, mark: Decimal | None) -> None:
    unrealized, equity = ledger.snapshot(mark)
    assert equity == ledger.balance_equity(mark)
    assert equity == q(ledger.starting_cash + ledger.realized_pnl + unrealized)


def test_starting_cash_and_notional_cap():
    ledger = _ledger()
    assert ledger.cash_free == Decimal("300")
    assert ledger.max_notional == Decimal("10")
    rejected = ledger.open_position("BTC", "long", Decimal("100"), T0, Decimal("10.01"))
    assert rejected.status == "rejected"
    assert rejected.rejection_reason == NOTIONAL_EXCEEDS_LIMIT
    assert ledger.position is None
    assert ledger.cash_free == Decimal("300")


def test_long_round_trip_fees_and_holding_period():
    ledger = _ledger()
    opened = ledger.open_position("BTC", "long", Decimal("100"), T0, Decimal("10"))
    assert opened.status == "filled"
    assert opened.notional == Decimal("10")
    assert opened.quantity == Decimal("0.1")
    assert opened.fee == Decimal("0.06")
    assert opened.fill_price == Decimal("100")
    assert ledger.cash_free == Decimal("289.94")
    assert ledger.locked_notional == Decimal("10")
    assert ledger.realized_pnl == Decimal("0")
    unrealized, equity = ledger.snapshot(Decimal("100"))
    assert unrealized == Decimal("-0.06")
    assert equity == Decimal("299.94")
    _assert_identity(ledger, Decimal("105"))
    marked, marked_equity = ledger.snapshot(Decimal("105"))
    assert marked == Decimal("0.44")
    assert marked_equity == Decimal("300.44")

    duplicate = ledger.open_position("SOL", "long", Decimal("100"), T0, Decimal("10"))
    assert duplicate.rejection_reason == POSITION_ALREADY_OPEN
    assert ledger.cash_free == Decimal("289.94")

    closed = ledger.close_position("BTC", "long", Decimal("110"), T1)
    assert closed.status == "filled"
    assert closed.fee == Decimal("0.066")
    assert closed.trade_realized_pnl == Decimal("0.874")
    assert closed.holding_seconds == 7200
    assert ledger.realized_pnl == Decimal("0.874")
    assert ledger.unrealized(Decimal("110")) == Decimal("0")
    assert ledger.cash_free == Decimal("300.874")
    assert ledger.locked_notional == Decimal("0")
    assert ledger.position is None
    _assert_identity(ledger, None)
    assert ledger.snapshot(None)[1] == Decimal("300.874")


def test_short_round_trip_does_not_increase_spendable_cash():
    ledger = _ledger()
    opened = ledger.open_position("SOL", "short", Decimal("100"), T0, Decimal("10"))
    assert opened.status == "filled"
    assert opened.notional <= Decimal("10")
    assert ledger.cash_free == Decimal("289.94")
    assert ledger.locked_notional == Decimal("10")
    assert ledger.realized_pnl == Decimal("0")
    unrealized, _equity = ledger.snapshot(Decimal("100"))
    assert unrealized == Decimal("-0.06")
    _assert_identity(ledger, Decimal("90"))

    mismatch = ledger.close_position("BTC", "short", Decimal("90"), T1)
    assert mismatch.rejection_reason == SYMBOL_MISMATCH
    assert ledger.position is not None

    closed = ledger.close_position("SOL", "short", Decimal("90"), T1)
    assert closed.fee == Decimal("0.054")
    assert closed.trade_realized_pnl == Decimal("0.886")
    assert ledger.cash_free == Decimal("300.886")
    assert ledger.realized_pnl == Decimal("0.886")
    assert ledger.position is None
    _assert_identity(ledger, None)


def test_slippage_is_adverse_and_size_shrinks_to_cash():
    ledger = _ledger(slippage_bps=Decimal("5"))
    opened = ledger.open_position("BTC", "long", Decimal("100"), T0, Decimal("10"))
    assert opened.fill_price > Decimal("100")
    assert opened.notional <= Decimal("10")
    assert opened.fee == q(opened.notional * Decimal("0.006"))
    closed = ledger.close_position("BTC", "long", Decimal("100"), T1)
    assert closed.fill_price < Decimal("100")

    short = _ledger(slippage_bps=Decimal("5"))
    short_open = short.open_position("BTC", "short", Decimal("100"), T0, Decimal("10"))
    assert short_open.fill_price < Decimal("100")
    short_close = short.close_position("BTC", "short", Decimal("100"), T1)
    assert short_close.fill_price > Decimal("100")

    small = _ledger(starting_cash=Decimal("5"))
    sized = small.open_position("BTC", "long", Decimal("100"), T0, Decimal("10"))
    assert sized.status == "filled"
    assert sized.notional < Decimal("10")
    assert sized.notional >= Decimal("1")
    assert sized.notional + sized.fee <= Decimal("5")

    refused = PaperLedger(starting_cash=Decimal("0.50"), slippage_bps=Decimal("0"))
    refused.seed(T0)
    result = refused.open_position("BTC", "long", Decimal("100"), T0, Decimal("10"))
    assert result.rejection_reason == INSUFFICIENT_CASH
    assert refused.cash_free == Decimal("0.50")
