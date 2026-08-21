"""Linux backend - nativni SPI / GPIO cdev / serial.

Zavislost:  pip install python-periphery

Proc periphery a ne gpiod:
  - libgpiod 1.6 (Debian bookworm) a 2.x maji nekompatibilni Python API,
    periphery to schova
  - nepotrebuje systemovy balicek, jde o cisty python nad /dev/gpiochip*
  - edge eventy nesou kernelovy CLOCK_MONOTONIC timestamp
"""

from __future__ import annotations

from typing import Sequence

from periphery import GPIO as _GPIO
from periphery import SPI as _SPI
from periphery import Serial as _Serial

from .base import EdgeEvent, GpioIn, GpioOut, Hal, SpiBus, Uart
from .config import PINOUT, GpioSpec, Pinout

# Tabulka pro obraceni poradi bitu v bajtu.
_BITREV = bytes(int(format(i, "08b")[::-1], 2) for i in range(256))


class LinuxSpi(SpiBus):
    """SPI slave nad jednim spidev nodem.

    ECSPI radic v i.MX8 nepodporuje SPI_LSB_FIRST. PN532 pritom LSB-first
    vyzaduje. Kdyz nastaveni na urovni driveru selze, prepneme se na
    softwarove obraceni bitu - navenek se to chova stejne.
    """

    def __init__(self, path: str, max_speed_hz: int, mode: int = 0,
                 bit_order: str = "msb"):
        self._spi = _SPI(path, mode, max_speed_hz)
        self._soft_lsb = False
        self._want = bit_order
        if bit_order == "lsb":
            try:
                self._spi.bit_order = "lsb"
            except Exception:
                self._soft_lsb = True

    @staticmethod
    def _rev(data: Sequence[int]) -> list[int]:
        return [_BITREV[b & 0xFF] for b in data]

    def transfer(self, data: Sequence[int]) -> list[int]:
        if self._soft_lsb:
            return self._rev(self._spi.transfer(self._rev(data)))
        return self._spi.transfer(list(data))

    def write(self, data: Sequence[int]) -> None:
        self._spi.transfer(self._rev(data) if self._soft_lsb else list(data))

    @property
    def soft_lsb(self) -> bool:
        """True = bity obracime v software, protoze radic to neumi."""
        return self._soft_lsb

    @property
    def bit_order(self) -> str:
        return self._want

    @bit_order.setter
    def bit_order(self, value: str) -> None:
        self._want = value
        self._soft_lsb = False
        try:
            self._spi.bit_order = value
        except Exception:
            if value == "lsb":
                self._soft_lsb = True
            else:
                raise

    def close(self) -> None:
        self._spi.close()


class LinuxGpioOut(GpioOut):
    def __init__(self, spec: GpioSpec, initial: bool = False):
        self._gpio = _GPIO(spec.chip, spec.line, "out")
        if spec.active_low:
            self._gpio.inverted = True
        self._gpio.write(initial)

    def write(self, value: bool) -> None:
        self._gpio.write(value)

    def close(self) -> None:
        self._gpio.close()


class LinuxGpioIn(GpioIn):
    def __init__(self, spec: GpioSpec, edge: str = "both"):
        self._gpio = _GPIO(spec.chip, spec.line, "in", edge=edge,
                           bias=spec.bias)
        if spec.active_low:
            self._gpio.inverted = True

    def read(self) -> bool:
        return self._gpio.read()

    def poll(self, timeout_s: float | None) -> bool:
        return self._gpio.poll(timeout_s)

    def read_event(self) -> EdgeEvent:
        ev = self._gpio.read_event()
        return EdgeEvent(edge=ev.edge, timestamp_ns=ev.timestamp)

    def close(self) -> None:
        self._gpio.close()


class LinuxUart(Uart):
    def __init__(self, path: str, baud: int):
        self._ser = _Serial(path, baud)

    def write(self, data: bytes) -> int:
        return self._ser.write(data)

    def read(self, n: int, timeout_s: float | None = None) -> bytes:
        return self._ser.read(n, timeout_s)

    def close(self) -> None:
        self._ser.close()


class LinuxHal(Hal):
    def __init__(self, pinout: Pinout = PINOUT):
        self.pinout = pinout
        self._open: list = []

    def _track(self, obj):
        self._open.append(obj)
        return obj

    def spi_pn532(self) -> SpiBus:
        # PN532 po SPI komunikuje LSB-first
        return self._track(LinuxSpi(self.pinout.spi_pn532_dev,
                                    self.pinout.spi_pn532_hz,
                                    mode=0, bit_order="lsb"))

    def spi_leds(self) -> SpiBus:
        return self._track(LinuxSpi(self.pinout.spi_leds_dev,
                                    self.pinout.spi_leds_hz,
                                    mode=0, bit_order="msb"))

    def gpio_out(self, name: str) -> GpioOut:
        return self._track(LinuxGpioOut(self.pinout.outputs[name]))

    def gpio_in(self, name: str, edge: str = "both") -> GpioIn:
        return self._track(LinuxGpioIn(self.pinout.inputs[name], edge=edge))

    def uart_servo(self) -> Uart:
        return self._track(LinuxUart(self.pinout.uart_servo_dev,
                                     self.pinout.uart_servo_baud))

    def close(self) -> None:
        for obj in reversed(self._open):
            try:
                obj.close()
            except Exception:
                pass
        self._open.clear()
