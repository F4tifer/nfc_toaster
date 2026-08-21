"""Mock backend - zadny hardware.

Ucel: pustit NestGuard / sort cyklus / ProvisionLog v unit testech na
macOS i v CI. Zaznamenava vse, co do nej logika zapsala, aby se dalo
asertovat "servo dostalo prikaz eject" apod.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Sequence

from .base import EdgeEvent, GpioIn, GpioOut, Hal, SpiBus, Uart


class MockSpi(SpiBus):
    def __init__(self, name: str, responses: deque | None = None):
        self.name = name
        self.written: list[list[int]] = []
        self.responses = responses if responses is not None else deque()
        self._bit_order = "msb"

    def transfer(self, data: Sequence[int]) -> list[int]:
        self.written.append(list(data))
        if self.responses:
            return list(self.responses.popleft())
        return [0] * len(data)

    def write(self, data: Sequence[int]) -> None:
        self.written.append(list(data))

    @property
    def bit_order(self) -> str:
        return self._bit_order

    @bit_order.setter
    def bit_order(self, value: str) -> None:
        self._bit_order = value

    def close(self) -> None:
        pass


class MockGpioOut(GpioOut):
    def __init__(self, name: str):
        self.name = name
        self.history: list[tuple[float, bool]] = []
        self.value = False

    def write(self, value: bool) -> None:
        self.value = value
        self.history.append((time.monotonic(), value))

    def close(self) -> None:
        pass


class MockGpioIn(GpioIn):
    """Hrany se do nej vkladaji testem pres inject()."""

    def __init__(self, name: str):
        self.name = name
        self.value = False
        self._events: deque[EdgeEvent] = deque()

    def inject(self, edge: str, at_ns: int | None = None) -> None:
        self._events.append(
            EdgeEvent(edge=edge, timestamp_ns=at_ns or time.monotonic_ns())
        )
        self.value = edge == "rising"

    def read(self) -> bool:
        return self.value

    def poll(self, timeout_s: float | None) -> bool:
        return bool(self._events)

    def read_event(self) -> EdgeEvent:
        return self._events.popleft()

    def close(self) -> None:
        pass


class MockUart(Uart):
    def __init__(self, name: str):
        self.name = name
        self.written = bytearray()
        self.to_read = bytearray()

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def read(self, n: int, timeout_s: float | None = None) -> bytes:
        out = bytes(self.to_read[:n])
        del self.to_read[:n]
        return out

    def close(self) -> None:
        pass


class MockHal(Hal):
    def __init__(self):
        self.spis: dict[str, MockSpi] = {}
        self.outputs: dict[str, MockGpioOut] = {}
        self.inputs: dict[str, MockGpioIn] = {}
        self.uarts: dict[str, MockUart] = {}

    def spi_pn532(self) -> SpiBus:
        return self.spis.setdefault("pn532", MockSpi("pn532"))

    def spi_leds(self) -> SpiBus:
        return self.spis.setdefault("leds", MockSpi("leds"))

    def gpio_out(self, name: str) -> GpioOut:
        return self.outputs.setdefault(name, MockGpioOut(name))

    def gpio_in(self, name: str, edge: str = "both") -> GpioIn:
        return self.inputs.setdefault(name, MockGpioIn(name))

    def uart_servo(self) -> Uart:
        return self.uarts.setdefault("servo", MockUart("servo"))

    def close(self) -> None:
        pass
