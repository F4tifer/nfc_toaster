"""Vyber backendu.

    TOASTER_HAL=linux   -> nativni SPI/GPIO na Toradexu (default na Linuxu)
    TOASTER_HAL=ft232h  -> stavajici Blinka implementace (macOS i Linux/USB)
    TOASTER_HAL=mock    -> bez hardwaru, pro testy

Import se dela lazy, aby mock backend nevyzadoval periphery a linux
backend nevyzadoval Blinku.
"""

from __future__ import annotations

import os
import platform

from .base import EdgeEvent, GpioIn, GpioOut, Hal, SpiBus, Uart

__all__ = ["get_hal", "Hal", "SpiBus", "GpioIn", "GpioOut", "Uart", "EdgeEvent"]


def _default_backend() -> str:
    return "linux" if platform.system() == "Linux" else "ft232h"


def get_hal(backend: str | None = None) -> Hal:
    name = (backend or os.environ.get("TOASTER_HAL") or _default_backend()).lower()

    if name == "linux":
        from .linux import LinuxHal
        return LinuxHal()
    if name == "ft232h":
        # sem prijde obal nad stavajici Blinka implementaci
        from .ft232h import Ft232hHal
        return Ft232hHal()
    if name == "mock":
        from .mock import MockHal
        return MockHal()

    raise ValueError(f"neznamy TOASTER_HAL backend: {name!r}")
