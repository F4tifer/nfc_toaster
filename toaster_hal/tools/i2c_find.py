import sys, os, errno, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from periphery import I2C

SKIP = []          # <- sem cisla vnitrnich sbernic z 'ls', napr. [2]
ADDR = 0x20

for n in (2, 3, 4, 5):
    if n in SKIP:
        print(f"i2c-{n}: preskoceno (vnitrni)")
        continue
    try:
        bus = I2C(f"/dev/i2c-{n}")
    except OSError as e:
        print(f"i2c-{n}: nelze otevrit ({e})")
        continue
    t = time.monotonic()
    try:
        bus.transfer(ADDR, [I2C.Message([0x00], read=True)])
        r = "ACK  <<< tady je expander"
    except OSError as e:
        r = errno.errorcode.get(e.errno, e.errno)
    print(f"i2c-{n}: {r}  ({(time.monotonic()-t)*1000:.0f} ms)")
    bus.close()
