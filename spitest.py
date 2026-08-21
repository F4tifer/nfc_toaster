#!/usr/bin/env python3
import spidev, time

def rev(b):  # bitova reverze uvnitr bajtu
    return int(f"{b:08b}"[::-1], 2)

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 500000
spi.mode = 0

def tx(data):
    return [rev(x) for x in spi.xfer2([rev(x) for x in data])]

# GetFirmwareVersion
frame = [0x01, 0x00, 0x00, 0xFF, 0x02, 0xFE, 0xD4, 0x02, 0x2A, 0x00]
time.sleep(0.005)
tx(frame)

for i in range(100):            # status polling
    time.sleep(0.005)
    st = tx([0x02, 0x00])[1]
    if st & 0x01:
        print(f"ready po {i} pokusech")
        break
else:
    print("STATUS NIKDY READY -> modul neposloucha (HSU? jumpery?)")
    raise SystemExit(1)

ack = tx([0x03] + [0x00] * 6)[1:]
print("ACK:", " ".join(f"{b:02x}" for b in ack))
print("ocekavano: 00 00 ff 00 ff 00")
