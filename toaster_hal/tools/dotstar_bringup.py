#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dotstar_bringup.py - oziveni SK9822 pasku na Toradexu.

Poradi, ve kterem to pouzivat:

  0. ZMER ZEM. Odpor mezi GND pasku a zemnim pinem X27 musi byt pod 1 ohm.
     Pasek a Toradex maji vlastni zdroje; bez svazane zeme nema signal
     referenci a pasek se chova NEDETERMINISTICKY - stejny prikaz da
     pokazde jiny vysledek. Zadny z testu nize to nepozna, protoze kazdy
     jednotlivy beh vypada jako svebytna chyba protokolu.
  1. ./dotstar_bringup.py probe        # sviti neco vubec? kolik LED? kterym smerem?
  2. ./dotstar_bringup.py rgb          # sedi barevne poradi (BGR vs RGB)?
  3. ./dotstar_bringup.py white --bri 31   # tady merit proud na 5V railu
  4. ./dotstar_bringup.py nests        # stavove barvy dle proposalu
  5. ./dotstar_bringup.py fps          # zatez CPU, rozhoduje o overlay
  6. ./dotstar_bringup.py pulse        # jak to vypada realne

Kdyz se vysledek mezi behy meni, nehledej chybu v protokolu. Mer zem.

Backend se prepina globalne:
  --backend bitbang            (vychozi, 2 GPIO, bez overlay)
  --backend spi --dev /dev/spidev2.0   (spi-gpio overlay nebo ECSPI2)

Stejny test na obou backendech = primy dukaz, jestli overlay stoji za to.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

# periphery i hal/ jsou v korenu projektu. Odvodit ho z umisteni skriptu,
# ne z CWD - relativni ".." funguje jen kdyz stojis prave v tools/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hal.pixels import (  # noqa: E402
    LEDS_PER_NEST,
    NESTS,
    blank,
    build_frame,
    open_pixels,
    solid,
)

# Barvy stavu hnizda dle proposalu.
STATES = {
    "empty": (255, 255, 255),
    "prov": (255, 120, 0),
    "ok": (0, 255, 0),
    "nok": (255, 0, 0),
}


# ------------------------------------------------------------------ prikazy


def cmd_probe(bus, a):
    """Rozsviti LED po jedne. Rekne delku retezce i orientaci pasku.

    Jediny test, kde ma kazda LED jina data. Vsechny ostatni posilaji do
    celeho retezce totez, takze posun o jednu pozici nepoznaji.

    Kdyby se rozsvitila jen prvni a dal nic, je pravdepodobne zapojeny
    vystupni konec (DO/CO) misto vstupniho (DI/CI). Sipky na pasku musi
    smerovat OD Pixel Shifteru.
    """
    n = a.leds
    print(f"projizdim {n} LED, {a.step} s na kus - Ctrl-C ukonci")
    try:
        for i in range(n):
            px = [((0, 0, 0), 0)] * n
            px[i] = ((255, 255, 255), a.bri)
            bus.write(build_frame(px))
            print(f"  LED {i}", end="\r", flush=True)
            time.sleep(a.step)
    finally:
        bus.write(blank(n))
        print()


def cmd_rgb(bus, a):
    """R -> G -> B na celem retezci. Overuje poradi bajtu."""
    for name, rgb in (("cervena", (255, 0, 0)),
                      ("zelena", (0, 255, 0)),
                      ("modra", (0, 0, 255))):
        print(f"  {name}")
        bus.write(solid(a.leds, rgb, a.bri))
        time.sleep(1.5)
    bus.write(blank(a.leds))


def cmd_white(bus, a):
    """Plna bila - worst case pro napajeni. Proposal pocita 2,2 A na 36 LED."""
    print(f"bila, jas {a.bri}/31, {a.leds} LED - merit proud na 5V railu")
    bus.write(solid(a.leds, (255, 255, 255), a.bri))
    input("Enter zhasne...")
    bus.write(blank(a.leds))


def cmd_nests(bus, a):
    """Kazde hnizdo jednim stavem. Overuje indexaci (N-1)*9 az (N-1)*9+8."""
    order = ["empty", "prov", "ok", "nok"]
    px = []
    for n in range(a.nests):
        rgb = STATES[order[n % len(order)]]
        px.extend([(rgb, a.bri)] * a.per_nest)
        print(f"  hnizdo {n + 1}: {order[n % len(order)]}  "
              f"indexy {n * a.per_nest}..{n * a.per_nest + a.per_nest - 1}")
    bus.write(build_frame(px))
    input("Enter zhasne...")
    bus.write(blank(len(px)))


def cmd_fps(bus, a):
    """Kolik snimku za sekundu backend utahne + zatez CPU.

    Namereno 19. 8. 2026, bitbang, 20 LED: 54 FPS pri 100 % jadra.
    Plynulost tedy staci (pulz chce ~25 FPS), zatez ne.

      pod 20 FPS  -> pulz bude viditelne trhany
      100 % CPU   -> jedno jadro natrvalo + horsi latence ostatnich
                     vlaken pres GIL; resi spi-gpio overlay
    """
    n = a.leds
    frame = solid(n, (255, 120, 0), a.bri)
    print(f"{n} LED, {len(frame)} B na snimek, merim {a.secs} s...")

    t_cpu0 = time.process_time()
    t0 = time.perf_counter()
    count = 0
    while time.perf_counter() - t0 < a.secs:
        bus.write(frame)
        count += 1
    wall = time.perf_counter() - t0
    cpu = time.process_time() - t_cpu0
    bus.write(blank(n))

    fps = count / wall
    print(f"\n  {fps:7.1f} FPS")
    print(f"  {wall / count * 1000:7.2f} ms na snimek")
    print(f"  {cpu / wall * 100:7.1f} % CPU (1.0 jadro = 100 %)")
    print(f"  {len(frame) * 8 / (wall / count) / 1000:7.0f} kbit/s efektivni clock")


def cmd_pulse(bus, a):
    """Pulzujici oranzova - realny provozni stav PROVISIONING.

    Meni se pouze 5bitovy jas v LED ramci, barva zustava konstantni.
    Presne tak, jak to popisuje proposal.
    """
    n = a.leds
    lo, hi = 2, a.bri
    print(f"pulz {a.period} s, jas {lo}..{hi} - Ctrl-C ukonci")
    t0 = time.perf_counter()
    frames = 0
    try:
        while True:
            ph = ((time.perf_counter() - t0) % a.period) / a.period
            k = 0.5 - 0.5 * math.cos(2 * math.pi * ph)
            bri = int(round(lo + k * (hi - lo)))
            bus.write(solid(n, STATES["prov"], bri))
            frames += 1
            time.sleep(0.02)
    except KeyboardInterrupt:
        el = time.perf_counter() - t0
        print(f"\n  {frames / el:.1f} FPS vcetne sleepu")
    finally:
        bus.write(blank(n))


def cmd_off(bus, a):
    bus.write(blank(a.leds))
    print("zhasnuto")


# --------------------------------------------------------------------- main

CMDS = {
    "probe": cmd_probe,
    "rgb": cmd_rgb,
    "white": cmd_white,
    "nests": cmd_nests,
    "fps": cmd_fps,
    "pulse": cmd_pulse,
    "off": cmd_off,
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=sorted(CMDS))
    p.add_argument("--backend", default="bitbang",
                   choices=["bitbang", "spi", "mock"])
    p.add_argument("--dev", default="/dev/spidev2.0",
                   help="jen pro --backend spi")
    p.add_argument("--speed", type=int, default=1_000_000)
    p.add_argument("-n", "--leds", type=int, default=LEDS_PER_NEST * NESTS)
    p.add_argument("--per-nest", type=int, default=LEDS_PER_NEST)
    p.add_argument("--nests", type=int, default=NESTS)
    p.add_argument("--bri", type=int, default=8,
                   help="5bitovy jas 0..31, pozor na proud")
    p.add_argument("--step", type=float, default=0.25, help="probe: s na LED")
    p.add_argument("--secs", type=float, default=3.0, help="fps: doba mereni")
    p.add_argument("--period", type=float, default=1.6, help="pulse: perioda s")
    a = p.parse_args()

    if not 0 <= a.bri <= 31:
        p.error("--bri musi byt 0..31")

    kw = {"path": a.dev, "speed_hz": a.speed}
    try:
        bus = open_pixels(a.backend, **kw)
    except Exception as e:
        print(f"backend {a.backend} se neotevrel: {e}", file=sys.stderr)
        return 1

    print(f"backend={a.backend}"
          + (f" dev={a.dev} {a.speed / 1e6:.1f} MHz" if a.backend == "spi" else ""))
    try:
        CMDS[a.cmd](bus, a)
    finally:
        bus.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
