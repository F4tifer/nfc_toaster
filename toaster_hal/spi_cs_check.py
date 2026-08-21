#!/usr/bin/env python3
"""Overi, jestli SPI radic drzi CS po cely burst.

Proc to existuje: ECSPI na iMX8 v rezimu nativniho chip selectu deasertuje
SS mezi jednotlivymi slovy. PN532 pak kazdy bajt bere jako novou transakci
a ramec nikdy nesestavi. Standardni spi-loopback test tohle NEODHALI,
protoze propojka MOSI-MISO o CS nic nevi.

Otisk chyby:
    status read (2 bajty) projde a vraci 0x00  <- modul zije a odpovida
    zapis ramce (10 bajtu) modul ignoruje      <- nikdy se nestane ready

Pouziti:
    python3 tools/spi_cs_check.py            # nativni CS z device tree
    python3 tools/spi_cs_check.py --cs NAZEV # rucni CS pres GPIO z config.py

Ocekavany vysledek pri zdravem CS:
    READY po 0 pokusech
    ACK: 00 00 ff 00 ff 00
"""

import argparse
import sys
import time

from hal import get_hal
from pn532 import build_frame

CS_SETUP_S = 0.002
POLL_TRIES = 100
POLL_INTERVAL_S = 0.005


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cs", default=None,
                    help="nazev GPIO z config.py pro rucni CS "
                         "(bez tohoto se pouzije nativni CS radice)")
    args = ap.parse_args()

    hal = get_hal("linux")
    try:
        spi = hal.spi_pn532()
        cs = hal.gpio_out(args.cs) if args.cs else None

        if cs is not None:
            print(f"rucni CS pres {args.cs}")
            cs.write(True)
            time.sleep(0.05)
        else:
            print("nativni CS radice")

        def txn(data):
            if cs is None:
                return spi.transfer(list(data))
            cs.write(False)
            time.sleep(CS_SETUP_S)
            try:
                return spi.transfer(list(data))
            finally:
                cs.write(True)
                time.sleep(0.001)

        # probuzeni
        time.sleep(0.01)
        txn([0x00])
        time.sleep(0.01)

        # GetFirmwareVersion: 01 (DATAWRITE) + ramec
        txn([0x01] + list(build_frame([0xD4, 0x02])))

        st = None
        for i in range(POLL_TRIES):
            time.sleep(POLL_INTERVAL_S)
            st = txn([0x02, 0x00])[1]        # STATREAD
            if st & 0x01:
                print(f"READY po {i} pokusech")
                ack = txn([0x03] + [0x00] * 6)[1:]   # DATAREAD
                got = " ".join(f"{b:02x}" for b in ack)
                print(f"ACK:        {got}")
                print("ocekavano:  00 00 ff 00 ff 00")
                ok = list(ack) == [0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00]
                print("OK - CS je v poradku" if ok else "ACK nesedi")
                return 0 if ok else 1

        if st == 0xFF:
            print("STAT ff - MISO visi ve vzduchu.")
            print("  modul neposloucha: zkontroluj SEL0=0V / SEL1=3V3 a POWER CYCLE")
            print("  (PN532 cte konfiguraci rozhrani jen pri resetu)")
        else:
            print(f"STAT {st:02x} - modul zije a odpovida, ale ramec neprijal.")
            print("  podezreni na cvakajici CS -> nastav cs-gpios v device tree,")
            print("  nebo docasne pust s --cs a rucnim GPIO")
        return 1

    finally:
        hal.close()


if __name__ == "__main__":
    sys.exit(main())
