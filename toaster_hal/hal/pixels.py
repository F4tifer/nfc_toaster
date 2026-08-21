"""SK9822 / APA102 transport pro Toaster Tester.

Tri backendy se shodnym rozhranim PixelBus.write(bytes):

    BitbangPixels   2 GPIO pres python-periphery. Bezi hned, bez overlay.
    SpidevPixels    /dev/spidevN.0 - spi-gpio z overlay, nebo ECSPI2.
    MockPixels      bez hardwaru, jen si pamatuje posledni ramec.

Nad tim sedi led_status.py, ktery jen sklada ramce a vola bus.write().
Zadny backend nezna stavy hnizd - tohle je cista linka.

POZOR - tri veci, ktere se snadno rozbijou:

1) SPOLECNA ZEM. Pasek napajeny z RD-85A a Toradex napajeny odjinud musi
   mit svazanou zem, jinak nema 5V signal z Pixel Shifteru vuci pasku
   zadnou referenci. Projevi se to NEDETERMINISTICKY - stejny kod da
   pokazde jiny vysledek a vypada to jako chyba protokolu. Stalo nas to
   19. 8. 2026 cely den. Kdyz se pasek chova pokazde jinak, mer zem
   drive, nez zacnes sahat na format ramce.

2) NIKDY /dev/spidev0.0. Tam visi PN532. SK9822 nema chip select a kazdy
   clock, ktery na sbernici uvidi, si prelozi jako barevna data.

3) Bity jdou MSB-first. LinuxSpi v hal/linux.py ma kvuli PN532 zapnutou
   softwarovou LSB reverzi - tenhle modul ji obchazi a otevira si SPI
   sam s bit_order="msb". Nepredavat sem hal.spi_pn532().
"""

from __future__ import annotations

from typing import Sequence

# ---------------------------------------------------------------- pinout
#
# X27 pin 16 = GPIO4, gpiochip0 offset 13   -> DAT
# X27 pin 17 = GPIO5, gpiochip4 offset 1    -> CLK
#
# Pozn.: DAT a CLK lezi na RUZNYCH gpiochipech, takze je nelze nastavit
# jednim ioctl (libgpiod v2 to umi jen v ramci jednoho chipu). Bit-bang
# v Pythonu proto stoji 3 syscally na bit misto 2.

DAT_SPEC = ("/dev/gpiochip0", 13)
CLK_SPEC = ("/dev/gpiochip4", 1)

# Geometrie: 4 hnizda po 5 LED. Pozor, proposal na dvou mistech uvadi 9.
LEDS_PER_NEST = 5
NESTS = 4

Pixel = tuple[tuple[int, int, int], int]  # ((r, g, b), brightness 0..31)


# --------------------------------------------------------------- protokol


def build_frame(pixels: Sequence[Pixel]) -> bytes:
    """Sestavi ramec platny pro SK9822 i APA102.

    start frame   32x 0
    LED frame     0xE0|bri(5b), B, G, R      <- poradi BGR, ne RGB
    reset frame   32x 0                      <- SK9822 latchuje az na nem
    trailing      n/2 pulzu JEDNICEK         <- APA102 potrebuje doteceni

    Adafruit u pasku #2574 v lednu 2026 zamenil APA102 za SK9822 a starsi
    civky jsou porad v obehu. Tenhle ramec vyhovuje obema, takze se typ
    cipu nemusi resit ani konfigurovat:

      SK9822 vyzaduje reset frame 32 nul, jinak se zapsany snimek projevi
      az pri nasledujicim zapisu a pasek je o snimek pozadu.

      APA102 reset frame nezna, ale kazdy cip zpozdi data o pul hodinoveho
      cyklu, takze posledni LED potrebuje n/2 pulzu navic. Jednicky proto,
      ze 32 nul jsou pro APA102 k nerozeznani od start framu.

    Trailing NESMI byt delsi, nez je treba. 32 bitu jednicek je presne
    delka jednoho LED ramce a hlavicka 0xFF znamena jas 31, takze by se do
    retezce zapsala BILA naplno. Pri peti LED je spravna delka jeden bajt.
    """
    n = len(pixels)
    out = bytearray(b"\x00\x00\x00\x00")
    for (r, g, b), bri in pixels:
        out += bytes((0xE0 | (bri & 0x1F), b & 0xFF, g & 0xFF, r & 0xFF))
    out += b"\x00\x00\x00\x00"
    out += b"\xFF" * max(1, (n + 15) // 16)
    return bytes(out)


def solid(n: int, rgb: tuple[int, int, int], bri: int = 8) -> bytes:
    """Zkratka - cely retezec jednou barvou."""
    return build_frame([(rgb, bri)] * n)


def blank(n: int) -> bytes:
    """Zhasnuti. Jas 0, ne cerna barva - cipem pak netece PWM proud."""
    return build_frame([((0, 0, 0), 0)] * n)


def resync(bus: "PixelBus", n: int, times: int = 3) -> None:
    """Srovna retezec do zname synchronizace.

    Volat pri startu aplikace, drive nez se poprve nastavi stav hnizd.
    Pri bootu Toradexu jsou pady GPIO ve stavu po resetu, pasek cte samy
    0xFF (jas 31, bila) a muze byt uprostred rozdelaneho ramce. Jeden
    blank to nemusi srovnat.

    Pulldowny 10 kOhm na DAT a CLK to resi lip, protoze pasek zustane
    zhasnuty uz od zapnuti. Tohle je pojistka, kdyby na desce nebyly.
    """
    frame = blank(n)
    for _ in range(times):
        bus.write(frame)


# --------------------------------------------------------------- rozhrani


class PixelBus:
    """Kontrakt pro led_status.py."""

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> "PixelBus":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# --------------------------------------------------------------- bit-bang


class BitbangPixels(PixelBus):
    """2 GPIO, softwarovy clock.

    SK9822 ani APA102 nemaji casove naroky - clock smi byt libovolne
    pomaly i nepravidelny, data se zapisuji na nabeznou hranu. Proto tu
    nejsou zadne sleepy; brzdou je syscall, ne cip.

    Zmereno 19. 8. 2026 na 20 LED: 54 FPS, 18,4 ms na snimek, 100 % jadra.
    Plynulost tedy staci, ale zatez ne - viz poznamka u led_status.py
    o vynechavani prekresleni, kdyz zadne hnizdo neanimuje.

    Optimalizace: DAT se prepisuje jen kdyz se bit zmenil. Start, reset
    a trailing jsou souvisle bloky stejnych bitu, takze se na nich sahne
    na DAT jednou misto desitek.
    """

    def __init__(self, dat_spec=DAT_SPEC, clk_spec=CLK_SPEC):
        from periphery import GPIO

        chip, line = dat_spec
        self._dat = GPIO(chip, line, "out")
        chip, line = clk_spec
        self._clk = GPIO(chip, line, "out")
        self._dat.write(False)
        self._clk.write(False)

    def write(self, data: bytes) -> None:
        dw = self._dat.write
        cw = self._clk.write
        last = False
        dw(False)
        for byte in data:
            for shift in (7, 6, 5, 4, 3, 2, 1, 0):
                bit = bool((byte >> shift) & 1)
                if bit is not last:
                    dw(bit)
                    last = bit
                cw(True)
                cw(False)

    def close(self) -> None:
        for obj in (self._dat, self._clk):
            try:
                obj.write(False)
                obj.close()
            except Exception:
                pass


# ----------------------------------------------------------------- spidev


class SpidevPixels(PixelBus):
    """Kernelove nebo hardwarove clockovani pres spidev.

    Dve moznosti, obe se pouzivaji stejne:
      - spi-gpio overlay nad GPIO4/GPIO5 -> in-kernel bit-bang, stejne draty
      - ECSPI2, pokud se ukaze, ze je nekam vyvedena

    CS se nezapojuje. spi-gpio se deklaruje s num-chipselects = <0>,
    u ECSPI2 se drat na CS proste neda - pasek ho ignoruje.
    """

    def __init__(self, path: str = "/dev/spidev2.0", speed_hz: int = 1_000_000):
        from periphery import SPI

        if path.startswith("/dev/spidev0."):
            raise ValueError(
                "spidev0.x je sbernice PN532. Pasek nema CS a "
                "interpretoval by provoz ctecek jako barvy."
            )
        self._spi = SPI(path, 0, speed_hz, bit_order="msb")
        self.path = path

    def write(self, data: bytes) -> None:
        self._spi.transfer(list(data))

    def close(self) -> None:
        try:
            self._spi.close()
        except Exception:
            pass


# ------------------------------------------------------------------- mock


class MockPixels(PixelBus):
    """Bez hardwaru. Uchova posledni ramec a pocet zapisu."""

    def __init__(self):
        self.last: bytes = b""
        self.writes: int = 0

    def write(self, data: bytes) -> None:
        self.last = bytes(data)
        self.writes += 1

    def decode(self, n: int | None = None) -> list[Pixel]:
        """Rozlozi posledni ramec zpet na pixely - pro asserty v testech.

        n je pocet ocekavanych LED. Bez nej se dekoduje az k prvnimu
        bajtu, ktery nevypada jako hlavicka - to ale nestaci, protoze
        trailing jednicek (0xFF) hlavicce odpovida. V testech n uvadej.
        """
        body = self.last[4:]
        px: list[Pixel] = []
        for i in range(0, len(body) - 3, 4):
            if n is not None and len(px) >= n:
                break
            head, b, g, r = body[i : i + 4]
            if head & 0xE0 != 0xE0:
                break
            px.append(((r, g, b), head & 0x1F))
        return px


# ---------------------------------------------------------------- factory


def open_pixels(backend: str = "bitbang", **kw) -> PixelBus:
    """backend: bitbang | spi | mock"""
    if backend == "bitbang":
        return BitbangPixels(
            kw.get("dat_spec", DAT_SPEC), kw.get("clk_spec", CLK_SPEC)
        )
    if backend == "spi":
        return SpidevPixels(
            kw.get("path", "/dev/spidev2.0"), kw.get("speed_hz", 1_000_000)
        )
    if backend == "mock":
        return MockPixels()
    raise ValueError(f"neznamy backend: {backend}")
