import pytest
from telarchy_example.metrics import clamp, metric_total


def test_metric_total_from_total():
    assert metric_total({"id": 1, "total": 42}) == 42.0


def test_metric_total_from_value():
    assert metric_total({"id": 1, "value": 3.14}) == pytest.approx(3.14)


def test_metric_total_prefers_total_over_value():
    assert metric_total({"id": 1, "total": 10, "value": 99}) == 10.0


def test_metric_total_missing_raises():
    with pytest.raises(ValueError):
        metric_total({"id": 1})


def test_clamp_within_range():
    assert clamp(5.0, 0.0, 10.0) == 5.0


def test_clamp_below_min():
    assert clamp(-1.0, 0.0, 10.0) == 0.0


def test_clamp_above_max():
    assert clamp(11.0, 0.0, 10.0) == 10.0


def test_clamp_at_boundaries():
    assert clamp(0.0, 0.0, 10.0) == 0.0
    assert clamp(10.0, 0.0, 10.0) == 10.0
