#!/usr/bin/env python3
"""Bring-up Toaster Testeru na Toradexu.

Pousti se po castech, odspodu nahoru. Kazdy krok je nezavisly, takze kdyz
neco nefunguje, vis presne co.

    python3 bringup.py devices          # co vubec existuje v /dev
    python3 bringup.py spi-loopback     # propoj MOSI-MISO drátkem
    python3 bringup.py blink power_en   # blikni vystupem
    python3 bringup.py watch ir_nest    # syrove hrany + timestampy
    python3 bringup.py capture ir_nest ir_chute --runs 30 --out timing.json

`capture` je ten dulezity: nasbira casove signatury z realnych pruchodu
karty, aby sly odvodit nove prahy pro NOK drop detection. Prahy z FT232H
verze NEPRENASEJ - USB polling mel jitter v jednotkach ms, tady jsi na
kernelovych prerusenich a jsi o dva rady jinde.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal import get_hal  # noqa: E402
from hal.config import PINOUT  # noqa: E402


def cmd_devices(_args) -> int:
    print("=== SPI ===")
    spis = sorted(glob.glob("/dev/spidev*"))
    print("\n".join(spis) if spis else
          "  ZADNY spidev! Chybi device tree overlay - viz README.")

    print("\n=== GPIO chipy ===")
    for chip in sorted(glob.glob("/dev/gpiochip*")):
        print(f"  {chip}")
    try:
        print()
        print(subprocess.run(["gpiodetect"], capture_output=True,
                             text=True).stdout.strip())
    except FileNotFoundError:
        print("  (gpiodetect nenainstalovan: apt install gpiod)")

    print("\n=== Serial ===")
    for pat in ("/dev/ttyACM*", "/dev/ttyUSB*", "/dev/ttymxc*"):
        for dev in sorted(glob.glob(pat)):
            print(f"  {dev}")

    print("\n=== Stabilni jmena (pouzij tato, ne ttyACM0) ===")
    byid = sorted(glob.glob("/dev/serial/by-id/*"))
    print("\n".join(f"  {p}" for p in byid) if byid else "  zadna")
    return 0


def cmd_spi_loopback(args) -> int:
    """Propoj MOSI a MISO drátkem. Bez propojky to vrati same 0x00 nebo 0xFF."""
    from hal.linux import LinuxSpi

    pattern = [0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0xFF, 0x55, 0xAA]
    spi = LinuxSpi(args.dev, args.hz, bit_order="msb")
    try:
        got = spi.transfer(pattern)
    finally:
        spi.close()

    print(f"poslano:  {[hex(x) for x in pattern]}")
    print(f"prijato:  {[hex(x) for x in got]}")
    if got == pattern:
        print("OK - loopback sedi, SPI zije")
        return 0
    print("NESEDI - zkontroluj propojku MOSI-MISO, mode a rychlost")
    return 1


def cmd_blink(args) -> int:
    hal = get_hal("linux")
    try:
        out = hal.gpio_out(args.name)
        print(f"blikam {args.name} ({PINOUT.outputs[args.name]}), Ctrl-C ukonci")
        while True:
            out.write(True)
            time.sleep(args.period / 2)
            out.write(False)
            time.sleep(args.period / 2)
    except KeyboardInterrupt:
        print("\nkonec")
        return 0
    finally:
        hal.close()


def cmd_watch(args) -> int:
    hal = get_hal("linux")
    try:
        pin = hal.gpio_in(args.name)
        print(f"sleduju {args.name}, klidova hodnota={pin.read()}, Ctrl-C ukonci")
        prev_ns = None
        while True:
            if not pin.poll(1.0):
                continue
            ev = pin.read_event()
            delta = "" if prev_ns is None else \
                f"  (+{(ev.timestamp_ns - prev_ns) / 1e6:.3f} ms)"
            prev_ns = ev.timestamp_ns
            print(f"{ev.edge:<8} {ev.timestamp_ns}{delta}")
    except KeyboardInterrupt:
        print("\nkonec")
        return 0
    finally:
        hal.close()


def cmd_capture(args) -> int:
    """Nasbira N pruchodu pres vic senzoru najednou pro kalibraci prahu."""
    import selectors

    hal = get_hal("linux")
    runs: list[list[dict]] = []
    current: list[dict] = []
    try:
        pins = {name: hal.gpio_in(name) for name in args.names}
        sel = selectors.DefaultSelector()
        for name, pin in pins.items():
            sel.register(pin._gpio.fd, selectors.EVENT_READ, name)

        print(f"sbiram {args.runs} pruchodu pres {', '.join(args.names)}")
        print(f"pruchod se uzavre po {args.gap}s ticha. Ctrl-C ukonci driv.\n")

        last_ns = None
        while len(runs) < args.runs:
            ready = sel.select(timeout=args.gap)
            if not ready:
                if current:
                    runs.append(current)
                    span = (current[-1]["t_ns"] - current[0]["t_ns"]) / 1e6
                    print(f"  pruchod {len(runs):>3}: "
                          f"{len(current)} hran, rozpeti {span:.2f} ms")
                    current = []
                    last_ns = None
                continue

            for key, _ in ready:
                name = key.data
                ev = pins[name].read_event()
                rel = 0.0 if last_ns is None else (ev.timestamp_ns - last_ns) / 1e6
                current.append({
                    "sensor": name,
                    "edge": ev.edge,
                    "t_ns": ev.timestamp_ns,
                    "delta_ms": round(rel, 4),
                })
                last_ns = ev.timestamp_ns
    except KeyboardInterrupt:
        print("\nprerusenо uzivatelem")
    finally:
        hal.close()

    if current:
        runs.append(current)

    if args.out and runs:
        with open(args.out, "w") as fh:
            json.dump({"sensors": args.names, "runs": runs}, fh, indent=2)
        print(f"\nulozeno do {args.out} ({len(runs)} pruchodu)")

    _summarize(runs)
    return 0


def _summarize(runs: list[list[dict]]) -> None:
    if not runs:
        print("nic nenasbirano")
        return
    spans = sorted((r[-1]["t_ns"] - r[0]["t_ns"]) / 1e6 for r in runs)
    n = len(spans)
    print(f"\ncelkove rozpeti pruchodu [ms] pres {n} vzorku:")
    print(f"  min    {spans[0]:.2f}")
    print(f"  p50    {spans[n // 2]:.2f}")
    print(f"  p95    {spans[min(int(n * 0.95), n - 1)]:.2f}")
    print(f"  max    {spans[-1]:.2f}")
    print("\nProhnat OK i NOK kartami zvlast a porovnat rozdelení - "
          "prah patri tam, kde se neprekryvaji.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices").set_defaults(fn=cmd_devices)

    sp = sub.add_parser("spi-loopback")
    sp.add_argument("--dev", default=PINOUT.spi_pn532_dev)
    sp.add_argument("--hz", type=int, default=1_000_000)
    sp.set_defaults(fn=cmd_spi_loopback)

    bl = sub.add_parser("blink")
    bl.add_argument("name")
    bl.add_argument("--period", type=float, default=1.0)
    bl.set_defaults(fn=cmd_blink)

    wa = sub.add_parser("watch")
    wa.add_argument("name")
    wa.set_defaults(fn=cmd_watch)

    ca = sub.add_parser("capture")
    ca.add_argument("names", nargs="+")
    ca.add_argument("--runs", type=int, default=30)
    ca.add_argument("--gap", type=float, default=1.5,
                    help="ticho [s], ktere uzavre pruchod")
    ca.add_argument("--out", default=None)
    ca.set_defaults(fn=cmd_capture)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
