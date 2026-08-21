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

CHIP SELECT - zmena oproti puvodnimu predpokladu (bring-up 2026-08):
    Nativni ECSPI chip select je pro PN532 nepouzitelny. Radic deasertuje
    SS mezi jednotlivymi slovy burstu, takze PN532 vidi kazdy bajt jako
    novou transakci a ramec nikdy nesestavi. Otisk chyby: status read
    (2 bajty) projde a vraci 0x00, zapis ramce (10 bajtu) modul ignoruje.
    spi-loopback test tohle NEODHALI, propojka o CS nic nevi.

    Reseni pro produkci: cs-gpios v device tree overlay, viz
    overlays/apalis-imx8_ecspi1-cs-gpio.dts.
    Docasny workaround pro bench: rucni CS pres GPIO1 (pn532_cs nize),
    drat prehozeny z X27 pin 9 na X27 pin 13.

    Az bude overlay hotovy, pn532_cs z outputs vyhod a PN532 instancuj
    bez cs= parametru.

Stejny problem se bude tykat i SC16IS752 bridge cipu na interface desce.

POZOR na X27: pin 10 = SPI1_MISO, pin 11 = SPI1_MOSI. Snadno se prohodi,
projevi se to ctenim samych 0xff (obe strany jsou vstupy, linka visi na
pull-upu).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GpioSpec:
    chip: str
    line: int
    bias: str = "default"       # pull_up / pull_down / disable / default
    active_low: bool = False
    initial: bool = False       # pocatecni hodnota vystupu, v logice PO
                                # aplikaci active_low


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
            # Rucni CS pro PN532. active_low necham False a v kodu se pracuje
            # s realnou urovni (False = sepnuto), aby bylo v pn532.py videt,
            # co se na dratu deje. initial=True = klidovy stav, nesepnuto.
            # Drat: X27 pin 13 (NE pin 9 - tam vede nativni CS radice).
            "pn532_cs": GpioSpec("/dev/gpiochip0", 8, initial=True),   # GPIO1 / MXM3_1
            "power_en": GpioSpec("/dev/gpiochip0", 9),                 # GPIO2 / MXM3_3
            # RSTO modulu. Zatim NEZAPOJENO - pouziva se jen s bringup --reset.
            # Az to zapojis, drat na X27 pin 18.
            "pn532_rst": GpioSpec("/dev/gpiochip4", 2, initial=True),  # GPIO6 / MXM3_13
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

    # Volne GPIO uz zadne nejsou. Az bude cs-gpios overlay, uvolni se GPIO1;
    # do te doby je vsech sest obsazenych.


PINOUT = Pinout()
