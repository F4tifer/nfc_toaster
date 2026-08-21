"""PN532 pres SPI, postavene nad hal.SpiBus.

Zamerne minimalisticke - jen to, co Toaster Tester potrebuje:
firmware version, SAM config, cteni UID pasivniho targetu.

Poznamka k bit orderu: PN532 po SPI mluvi LSB-first. ECSPI radic v iMX8
to nepodporuje, ale LinuxSpi to resi softwarovym obracenim bitu, takze
tenhle modul posila normalni MSB bajty a o nic se nestara.

POZOR - chip select na iMX8 (bring-up 2026-08):
    Nativni ECSPI chip select je pro PN532 NEPOUZITELNY. Radic deasertuje
    SS mezi jednotlivymi slovy burstu, takze PN532 vidi kazdy bajt jako
    novou transakci a ramec nikdy nesestavi. Projevuje se to tak, ze
    status read (2 bajty) projde a vraci 0x00, ale zapis ramce (10 bajtu)
    modul ignoruje - nikdy se nestane ready.

    Reseni: v device tree overlay nastavit ecspi1 cs-gpios, viz
    overlays/apalis-imx8_ecspi1-cs-gpio.dts. Pak spidev drzi CS korektne
    po cely burst a tenhle modul funguje beze zmeny.

    Diagnostika: tools/spi_cs_check.py
    Pozor - spi-loopback test tuhle chybu NEODHALI, drat o CS nevi.
"""

from __future__ import annotations

import time
from typing import Sequence

from hal.base import GpioOut, SpiBus

# ramcove prefixy (prvni bajt kazde SPI transakce)
_SPI_DATAWRITE = 0x01
_SPI_STATREAD = 0x02
_SPI_DATAREAD = 0x03

_PREAMBLE = 0x00
_STARTCODE1 = 0x00
_STARTCODE2 = 0xFF
_POSTAMBLE = 0x00

_HOSTTOPN532 = 0xD4
_PN532TOHOST = 0xD5

_ACK = bytes([0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00])

# PN532 potrebuje po sestupne hrane CS chvili, nez zacne vzorkovat hodiny.
# Datasheet mluvi o ~1ms, 2ms je bezpecna rezerva a na propustnost to nema
# vliv - provisioning karty stejne trva radove stovky ms.
_CS_SETUP_S = 0.002

CMD_GET_FIRMWARE_VERSION = 0x02
CMD_SAM_CONFIGURATION = 0x14
CMD_IN_LIST_PASSIVE_TARGET = 0x4A

MIFARE_ISO14443A = 0x00


class PN532Error(Exception):
    pass


class PN532Timeout(PN532Error):
    pass


def build_frame(data: Sequence[int]) -> bytes:
    """Sestavi normal information frame.

    GetFirmwareVersion (D4 02) -> 00 00 FF 02 FE D4 02 2A 00
    """
    if not 1 <= len(data) <= 255:
        raise PN532Error(f"nepodporovana delka ramce: {len(data)}")

    length = len(data)
    lcs = (~length + 1) & 0xFF
    checksum = (~sum(data) + 1) & 0xFF

    return bytes(
        [_PREAMBLE, _STARTCODE1, _STARTCODE2, length, lcs]
        + list(data)
        + [checksum, _POSTAMBLE]
    )


class PN532:
    def __init__(self, spi: SpiBus, reset: GpioOut | None = None,
                 cs: GpioOut | None = None, debug: bool = False):
        """
        spi   - sbernice z hal.spi_pn532()
        reset - volitelny RSTO pin modulu
        cs    - volitelny rucni chip select. Nech None, pokud mas v device
                tree spravne nastavene cs-gpios (doporuceno). Pouzij jen
                jako docasny workaround, kdyz overlay jeste nemas -
                casovani z Pythonu ma znatelny jitter.
        """
        self._spi = spi
        self._reset = reset
        self._cs = cs
        self._debug = debug
        if cs is not None:
            cs.write(True)          # CS je active-low, klid = high
            time.sleep(0.05)
        if reset is not None:
            self.hard_reset()
        self._wakeup()

    # --- nizka uroven ---

    def _txn(self, data: Sequence[int]) -> list[int]:
        """Jedna SPI transakce. CS drzi dole po celou dobu."""
        if self._cs is None:
            return self._spi.transfer(list(data))

        self._cs.write(False)
        time.sleep(_CS_SETUP_S)
        try:
            return self._spi.transfer(list(data))
        finally:
            self._cs.write(True)
            time.sleep(0.001)

    def hard_reset(self) -> None:
        if self._reset is None:
            return
        self._reset.write(True)
        time.sleep(0.1)
        self._reset.write(False)
        time.sleep(0.5)
        self._reset.write(True)
        time.sleep(0.1)

    def _wakeup(self) -> None:
        """PN532 potrebuje po nabehnuti CS chvili, nez zacne odpovidat."""
        time.sleep(0.01)
        self._txn([0x00])
        time.sleep(0.01)

    def _status_ready(self) -> bool:
        st = self._txn([_SPI_STATREAD, 0x00])[1]
        if self._debug:
            print(f"STAT {st:02x}")
        return bool(st & 0x01)

    def _wait_ready(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._status_ready():
                return
            time.sleep(0.005)
        raise PN532Timeout(
            f"PN532 neodpovedel do {timeout}s "
            "(pokud STAT porad 00, podezreni na cvakajici CS - viz docstring)"
        )

    def _write_frame(self, data: Sequence[int]) -> None:
        frame = build_frame(data)
        if self._debug:
            print("TX", frame.hex(" "))
        self._txn([_SPI_DATAWRITE] + list(frame))

    def _read_raw(self, count: int) -> bytes:
        got = self._txn([_SPI_DATAREAD] + [0x00] * count)
        return bytes(got[1:])

    def _read_ack(self) -> None:
        got = self._read_raw(len(_ACK))
        if self._debug:
            print("ACK", got.hex(" "))
        if got != _ACK:
            raise PN532Error(f"ocekavan ACK, prislo {got.hex(' ')}")

    def _read_frame(self, max_len: int) -> bytes:
        """Vrati payload za TFI (tj. bez command echa uz ne - to necha volajici)."""
        raw = self._read_raw(max_len + 8)
        if self._debug:
            print("RX", raw.hex(" "))

        # najdi start 00 FF - pred nim byva promenlivy pocet 00
        idx = raw.find(b"\x00\xff")
        if idx < 0:
            raise PN532Error(f"nenalezen start ramce v {raw.hex(' ')}")
        body = raw[idx + 2:]

        if len(body) < 3:
            raise PN532Error("ramec je prilis kratky")

        length, lcs = body[0], body[1]
        if (length + lcs) & 0xFF:
            raise PN532Error(f"spatny LCS: len={length:#04x} lcs={lcs:#04x}")

        payload = body[2:2 + length]
        if len(payload) < length:
            raise PN532Error("neuplny ramec")
        if payload[0] != _PN532TOHOST:
            raise PN532Error(f"spatny TFI: {payload[0]:#04x}")

        dcs = body[2 + length]
        if (sum(payload) + dcs) & 0xFF:
            raise PN532Error("spatny DCS")

        return payload[1:]

    def call(self, command: int, params: Sequence[int] = (),
             response_len: int = 0, timeout: float = 1.0) -> bytes:
        self._write_frame([_HOSTTOPN532, command] + list(params))
        self._wait_ready(timeout)
        self._read_ack()
        if response_len == 0:
            return b""
        self._wait_ready(timeout)
        resp = self._read_frame(response_len)
        if not resp or resp[0] != command + 1:
            raise PN532Error(
                f"odpoved na jiny prikaz: {resp[:1].hex()} != {command + 1:#04x}"
            )
        return resp[1:]

    # --- vysoka uroven ---

    def get_firmware_version(self) -> tuple[int, int, int, int]:
        """Vraci (IC, Ver, Rev, Support). Pro PN532 je IC = 0x32."""
        r = self.call(CMD_GET_FIRMWARE_VERSION, response_len=4, timeout=0.5)
        if len(r) != 4:
            raise PN532Error(f"ocekavany 4 bajty, prislo {len(r)}")
        return r[0], r[1], r[2], r[3]

    def sam_configuration(self) -> None:
        """Normal mode, bez timeoutu, IRQ pin nepouzivame."""
        self.call(CMD_SAM_CONFIGURATION, [0x01, 0x14, 0x01], response_len=0)

    def read_passive_target(self, card_baud: int = MIFARE_ISO14443A,
                            timeout: float = 1.0) -> bytes | None:
        """Vraci UID karty, nebo None kdyz v poli nic neni."""
        try:
            r = self.call(CMD_IN_LIST_PASSIVE_TARGET, [0x01, card_baud],
                          response_len=19, timeout=timeout)
        except PN532Timeout:
            return None
        if not r or r[0] != 0x01:      # pocet nalezenych targetu
            return None
        uid_len = r[5]
        return bytes(r[6:6 + uid_len])
