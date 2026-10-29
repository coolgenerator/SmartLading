import pytest
from conftest import tariff_signal

from smartlading.models import Brand, RiskSignal
from smartlading.models.p1 import FactoryPersona, Terms


def test_safety_line_days_of_fixed_cost():
    b = Brand(id="b", name="n", cash_balance=1, credit_limit=0, daily_fixed_cost=1000, safety_line_days=30)
    assert b.cash_safety_line == 30_000


def test_safety_line_fixed():
    b = Brand(
        id="b", name="n", cash_balance=1, credit_limit=0, daily_fixed_cost=1000,
        safety_line_mode="fixed", cash_safety_line_fixed=12_345,
    )
    assert b.cash_safety_line == 12_345


def test_fixed_mode_requires_amount():
    with pytest.raises(ValueError):
        Brand(id="b", name="n", cash_balance=1, credit_limit=0, daily_fixed_cost=1, safety_line_mode="fixed")


def test_quote_must_match_source():
    data = tariff_signal().model_dump()
    with pytest.raises(ValueError):
        RiskSignal.model_validate({**data, "quote": "made up"})


def test_factory_never_goes_below_floor():
    persona = FactoryPersona(min_prepay_ratio=0.25, min_quantity=3000, min_unit_cost=4.0)
    clamped = persona.clamp(Terms(prepay_ratio=0.1, quantity=1000, unit_cost=3.5))
    assert clamped == Terms(prepay_ratio=0.25, quantity=3000, unit_cost=4.0)
