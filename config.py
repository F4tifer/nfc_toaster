"""Mapovani logickych jmen na fyzicke prostredky.

Vyplneno podle skutecneho dumpu z Apalis iMX8 / Torizon OS 7.7.0.

DULEZITE - offsety jsou v ramci chipu, ne globalni cisla z
/sys/kernel/debug/gpio. gpiochip0 ma bazi 512, gpiochip4 bazi 640.

    Apalis    MXM3   global   chip  offset
    GPIO1        1      520      0       8
    GPIO2        3      521      0       9
    GPIO3        5      524      0      12
    GPIO4        7      525      0      13
    GPIO5       11      641      4       1
    GPIO6       13      642      4       2

GPIO7 (MXM3_15) a GPIO8 (MXM3_17) NEPOUZIVAT - zabrane driverem
(regulator-pcie-switch, gpio-fan).

CS piny SPI si spidev ridi sam pres cs-gpios (spi0 CS0 = MXM3_227,
spi1 CS0 = MXM3_233). Rucne se jich nedotykej.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GpioSpec:
    chip: str
    line: int
    bias: str = "default"       # pull_up / pull_down / disable / default
    active_low: bool = False


@dataclass(frozen=True)
class Pinout:
    # spi0 = Apalis SPI1 (MXM3 221/223/225/227)
    spi_pn532_dev: str = "/dev/spidev0.0"
    spi_pn532_hz: int = 1_000_000

    # spi1 = Apalis SPI2 (MXM3 229/231/233/235)
    # SK9822 nema CS, takze prepinani CS0 je neskodne
    spi_leds_dev: str = "/dev/spidev1.0"
    spi_leds_hz: int = 4_000_000

    # Maestro zatim nezapojene - /dev/serial/by-id/ jeste neexistuje.
    # Po zapojeni sem dej stabilni jmeno z by-id, ne ttyACM0.
    uart_servo_dev: str = "/dev/ttyACM0"
    uart_servo_baud: int = 9600

    outputs: dict[str, GpioSpec] = field(
        default_factory=lambda: {
            "pn532_rst": GpioSpec("/dev/gpiochip0", 8),    # GPIO1 / MXM3_1
            "power_en": GpioSpec("/dev/gpiochip0", 9),     # GPIO2 / MXM3_3
        }
    )

    inputs: dict[str, GpioSpec] = field(
        default_factory=lambda: {
            # bias uprav podle toho, jestli mas externi pullup na desce
            "ir_nest": GpioSpec("/dev/gpiochip0", 12, bias="pull_up"),   # GPIO3
            "ir_chute": GpioSpec("/dev/gpiochip0", 13, bias="pull_up"),  # GPIO4
            "ir_eject": GpioSpec("/dev/gpiochip4", 1, bias="pull_up"),   # GPIO5
        }
    )

    # volne k dispozici: GPIO6 = gpiochip4 offset 2 (MXM3_13)


PINOUT = Pinout()
