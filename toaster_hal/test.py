#!/usr/bin/env python3
import time
from hal import get_hal
from pn532 import build_frame

hal = get_hal("linux")
spi = hal.spi_pn532()
cs = hal.gpio_out("pn532_cs")     # uprav podle sveho PINOUT

def txn(data):
    cs.write(False)
    time.sleep(0.002)              # PN532 chce ~2ms po CS low
    out = spi.transfer(list(data))
    cs.write(True)
    time.sleep(0.001)
    return out

cs.write(True)
time.sleep(0.05)

txn([0x01] + list(build_frame([0xD4, 0x02])))

for i in range(100):
    time.sleep(0.005)
    st = txn([0x02, 0x00])[1]
    if st & 0x01:
        print(f"READY po {i} pokusech")
        ack = txn([0x03] + [0x00] * 6)[1:]
        print("ACK:", " ".join(f"{b:02x}" for b in ack))
        print("ocekavano: 00 00 ff 00 ff 00")
        break
else:
    print(f"porad {st:02x} - CS to nebyl, jdeme na osciloskop")

hal.close()
