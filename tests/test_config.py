from __future__ import annotations

import pytest

from heritage_explorer.config import port_number, positive_float, positive_int


def test_positive_runtime_values_reject_zero_and_negative(monkeypatch) -> None:
    monkeypatch.setenv("XUHUA_TEST_INT", "0")
    monkeypatch.setenv("XUHUA_TEST_FLOAT", "-0.5")

    with pytest.raises(ValueError, match="XUHUA_TEST_INT must be positive"):
        positive_int("XUHUA_TEST_INT")
    with pytest.raises(ValueError, match="XUHUA_TEST_FLOAT must be positive"):
        positive_float("XUHUA_TEST_FLOAT")


def test_port_number_enforces_tcp_port_range(monkeypatch) -> None:
    monkeypatch.setenv("XUHUA_TEST_PORT", "65535")
    assert port_number("XUHUA_TEST_PORT") == 65535

    monkeypatch.setenv("XUHUA_TEST_PORT", "65536")
    with pytest.raises(ValueError, match="between 1 and 65535"):
        port_number("XUHUA_TEST_PORT")
