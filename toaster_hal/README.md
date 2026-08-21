# Toaster Tester — portace na Toradex Apalis iMX8 / Ixora

## Krok 0 — FT232H přes USB do Ixory

Než sáhneš na nativní SPI, zastrč FT232H do USB portu Ixory a pusť **stávající
kód beze změny**:

```bash
docker run --rm -it --privileged -v $PWD:/app -w /app \
  python:3.11-slim-bookworm bash
pip install adafruit-blinka pyftdi
BLINKA_FT232H=1 python3 tvuj_stavajici_main.py
```

Když to projde, víš že kontejner, ARM64 build závislostí i logika jsou v pořádku.
Zbytek už je čistě HAL. Když neprojde, řešíš problém nesouvisející s Toradexem.

## Krok 1 — periferie v device tree

```bash
python3 bringup.py devices
```

Když chybí `/dev/spidev*`, potřebuješ overlay. Na Torizonu:

```bash
ls /boot/ostree/torizon-*/dtb/overlays/ | grep -i spi
cat /boot/ostree/torizon-*/usr/lib/modules/*/dtb/overlays.txt 2>/dev/null || \
  cat /boot/overlays.txt
```

Přidat overlay a rebootnout. Čistší cesta je `torizoncore-builder dto apply`,
protože ruční editace `overlays.txt` se ti ztratí při OTA updatu.

Pozor: Apalis iMX8 má gpiochipů víc než jeden. `gpioinfo` ukáže jména linek
z device tree — hledej podle nich, ne podle pořadových čísel.

## Krok 2 — vyplnit `hal/config.py`

Všechny hodnoty v `PINOUT` jsou placeholdery. Přepiš je podle výstupu
`gpiodetect` / `gpioinfo` / `ls /dev/spidev*`.

## Krok 3 — ověřit plumbing

```bash
pip install python-periphery
python3 bringup.py spi-loopback        # propojka MOSI–MISO
python3 bringup.py blink power_en
python3 bringup.py watch ir_nest
```

## Krok 4 — PN532

Dvě cesty:

**A) Blinka nativně** — nejmenší úprava kódu, `adafruit_pn532` zůstane beze
změny. Riziko: `adafruit_platformdetect` nemusí Apalis iMX8QM znát a je nutné
ho přinutit přes `BLINKA_FORCECHIP` / `BLINKA_FORCEBOARD`. Vyzkoušej, je to
otázka deseti minut.

**B) Vlastní tenký driver nad `hal.SpiBus`** — čistší, testovatelný přes
`MockHal`, žádná závislost na Blince v produkci. Víc práce.

Doporučuju zkusit A, a když se detekce nepovede rozumně zprovoznit, jít na B.

## Krok 5 — překalibrovat timing

**Tohle nepřeskakuj.** Prahy pro NOK drop detection a push-back detekci
odvozené na FT232H neplatí — USB polling měl jitter v jednotkách ms, nativní
edge eventy jsou pod 100 µs.

```bash
# 30 průchodů OK kartami
python3 bringup.py capture ir_nest ir_chute ir_eject --runs 30 --out ok.json
# 30 průchodů NOK kartami
python3 bringup.py capture ir_nest ir_chute ir_eject --runs 30 --out nok.json
```

Prahy patří tam, kde se rozdělení nepřekrývají.

## Krok 6 — servo

Zatím nech Maestro na USB (`/dev/ttyACM0`). Přechod na SC16IS752 dává smysl až
na produkční desce — teď by to byla další neznámá navíc a Maestro si navíc řeší
timing pulzů samo, takže tě netrápí nedeterminismus userspace na Linuxu.

Použij stabilní jméno, `ttyACM0` se umí přečíslovat:

```bash
ls -l /dev/serial/by-id/
```

## Krok 7 — kontejner

```yaml
services:
  toaster:
    image: toaster-tester:dev
    environment:
      TOASTER_HAL: linux
    devices:
      - /dev/spidev1.0
      - /dev/spidev1.1
      - /dev/gpiochip0
      - /dev/ttyACM0
    group_add: ["gpio", "spidev", "dialout"]
    volumes:
      - /home/torizon/data:/data      # ProvisionLog musí přežít restart
    restart: unless-stopped
```

Pro bring-up klidně `privileged: true`, utáhnout až potom.

## Poznámky k Torizonu

- Zapisovatelné a persistentní je `/home/torizon` a `/var`. Zbytek rootfs je
  OSTree a změny mimo tyto cesty ti sežere první OTA update.
- eMMC se docker images zaplní rychle — `docker system prune -a`.
- Bez správného času (NTP) selže TLS handshake s divnou chybou; `timedatectl`.
- SK9822 na 3,3 V datech bývá vrtkavé. Na Ixoře bez level shifteru čekej
  náhodné artefakty, zvlášť u delšího pásku.
