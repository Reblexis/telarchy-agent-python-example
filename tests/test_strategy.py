import pytest
from telarchy_example.strategy_untouched import (
    _safe_float,
    _liquidity_positive,
    _virgin_midpoint_equals_target,
    _VIRGIN_MID_TOL,
)


# _safe_float

def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_none_with_default():
    assert _safe_float(None, 0.0) == 0.0


def test_safe_float_bool_excluded():
    assert _safe_float(True) is None
    assert _safe_float(False) is None


def test_safe_float_int():
    assert _safe_float(42) == 42.0


def test_safe_float_float():
    assert _safe_float(3.14) == pytest.approx(3.14)


def test_safe_float_valid_string():
    assert _safe_float("3.14") == pytest.approx(3.14)


def test_safe_float_invalid_string():
    assert _safe_float("abc") is None


def test_safe_float_empty_string():
    assert _safe_float("") is None


# _liquidity_positive

def test_liquidity_positive_true():
    assert _liquidity_positive(1.0) is True
    assert _liquidity_positive("100") is True


def test_liquidity_zero_false():
    assert _liquidity_positive(0) is False


def test_liquidity_none_false():
    assert _liquidity_positive(None) is False


def test_liquidity_invalid_false():
    assert _liquidity_positive("abc") is False


# _virgin_midpoint_equals_target

def _market(consensus, rmin, rmax):
    return {"consensus": consensus, "rangeMin": rmin, "rangeMax": rmax}


def test_virgin_mid_detected():
    is_virgin, mid = _virgin_midpoint_equals_target(_market(None, 0, 1000), 500.0)
    assert is_virgin is True
    assert mid == pytest.approx(500.0)


def test_virgin_mid_not_triggered_when_consensus_set():
    is_virgin, mid = _virgin_midpoint_equals_target(_market(450.0, 0, 1000), 500.0)
    assert is_virgin is False
    assert mid is None


def test_virgin_mid_not_triggered_when_target_differs():
    # target far from midpoint (600 vs 500)
    is_virgin, mid = _virgin_midpoint_equals_target(_market(None, 0, 1000), 600.0)
    assert is_virgin is False
    assert mid is None


def test_virgin_mid_missing_range_keys():
    is_virgin, mid = _virgin_midpoint_equals_target({"consensus": None}, 500.0)
    assert is_virgin is False
    assert mid is None
