import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from periphery import I2C
import errno

BUS  = "/dev/i2c-4"     # <- doplnit podle kroku 2
ADDR = 0x20

IODIRA, IPOLA, GPPUA, GPIOA, IOCON = 0x00, 0x02, 0x0C, 0x12, 0x0A

i2c = I2C(BUS)

def probe(a):
    t = time.monotonic()
    try:
        i2c.transfer(a, [I2C.Message([0x00], read=True)])
        return "ACK", time.monotonic() - t
    except OSError as e:
        return errno.errorcode.get(e.errno, e.errno), time.monotonic() - t

res, dt = probe(ADDR)
print(f"0x20 -> {res}  ({dt*1000:.1f} ms)")

if res == "ETIMEDOUT":
    sys.exit("Sbernice nefunguje na fyzicke urovni. Zmer SDA a SCL proti GND,\n"
             "musi byt obe na 3,3 V. Zkontroluj cislo sbernice a piny X27.")
if res != "ACK":
    sys.exit(f"Sbernice jede, ale 0x20 neodpovida ({res}).\n"
             "Zkontroluj VIN a adresove propojky na spodni strane breakoutu.")

def wr(reg, val): i2c.transfer(ADDR, [I2C.Message([reg, val])])
def rd(reg):
    m = [I2C.Message([reg]), I2C.Message([0x00], read=True)]
    i2c.transfer(ADDR, m)
    return m[1].data[0]

wr(IOCON, 0x00); wr(IODIRA, 0xFF); wr(GPPUA, 0x00); wr(IPOLA, 0x00)
assert rd(IODIRA) == 0xFF, "zapis do IODIRA se nepotvrdil"

print("ctu GPIOA, Ctrl-C ukonci\n")
try:
    while True:
        v = rd(GPIOA)
        d = "KARTA" if not v & 0x01 else "volno"
        h = "KARTA" if not v & 0x02 else "volno"
        print(f"\rGPIOA={v:08b}  dolni={d}  horni={h}", end="", flush=True)
        time.sleep(0.1)
except KeyboardInterrupt:
    print()
finally:
    i2c.close()
