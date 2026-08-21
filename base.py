"""Hardware abstraction layer - abstraktni rozhrani.

Business logika (NestGuard, ProvisionLog, sort cyklus, led_status)
importuje VYHRADNE odsud. Zadny primy import spidev / periphery / board.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Sequence

Edge = Literal["rising", "falling"]


@dataclass(frozen=True)
class EdgeEvent:
    """Hrana na vstupnim GPIO.

    timestamp_ns je CLOCK_MONOTONIC z kernelu (u linux backendu), tzn.
    nezavisly na jitteru userspace smycky. U ft232h/mock backendu je to
    time.monotonic_ns() a presnost je radove horsi - viz README.
    """

    edge: Edge
    timestamp_ns: int


class SpiBus(ABC):
    """Jeden SPI slave (tj. spidev node vcetne sveho CS)."""

    @abstractmethod
    def transfer(self, data: Sequence[int]) -> list[int]:
        """Full-duplex prenos. Vraci prijata data stejne delky jako `data`."""

    @abstractmethod
    def write(self, data: Sequence[int]) -> None:
        """Zapis bez cteni (pro LED strip - setri alokace)."""

    @property
    @abstractmethod
    def bit_order(self) -> str:
        """'msb' nebo 'lsb'. PN532 chce 'lsb', SK9822 chce 'msb'."""

    @bit_order.setter
    @abstractmethod
    def bit_order(self, value: str) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class GpioOut(ABC):
    @abstractmethod
    def write(self, value: bool) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class GpioIn(ABC):
    @abstractmethod
    def read(self) -> bool: ...

    @abstractmethod
    def poll(self, timeout_s: float | None) -> bool:
        """Ceka na hranu. True = hrana je k dispozici pres read_event()."""

    @abstractmethod
    def read_event(self) -> EdgeEvent: ...

    @abstractmethod
    def close(self) -> None: ...


class Uart(ABC):
    @abstractmethod
    def write(self, data: bytes) -> int: ...

    @abstractmethod
    def read(self, n: int, timeout_s: float | None = None) -> bytes: ...

    @abstractmethod
    def close(self) -> None: ...


class Hal(ABC):
    """Tovarna na periferie. Konkretni backend implementuje tyto metody."""

    @abstractmethod
    def spi_pn532(self) -> SpiBus: ...

    @abstractmethod
    def spi_leds(self) -> SpiBus: ...

    @abstractmethod
    def gpio_out(self, name: str) -> GpioOut: ...

    @abstractmethod
    def gpio_in(self, name: str, edge: str = "both") -> GpioIn: ...

    @abstractmethod
    def uart_servo(self) -> Uart: ...

    def close(self) -> None:
        """Zavre vse, co backend drzi. Volat v finally / atexit."""
