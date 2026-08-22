#!/usr/bin/env python3
"""MAX30102 photocurrent and noise budget, from datasheet parameters.

Device constants are confirmed against the vendor library's own datasheet quotes:
  ADC LSB   7.81 / 15.63 / 31.25 / 62.5 pA for the 2048/4096/8192/16384 nA ranges
  LED step  0.2 mA per code   (0x7F -> 25.4 mA and 0xFF -> 51 mA both check out)
  ADC       18-bit  (the driver masks samples with 0x3FFFF)
Measured counts come from hardware captures in docs/pulse-ox/.
"""
import math
q = 1.602176634e-19
LSB = {2048: 7.81e-12, 4096: 15.63e-12, 8192: 31.25e-12, 16384: 62.5e-12}
FS_COUNTS = 2 ** 18
LED_STEP = 0.2e-3
PW = 411e-6          # active-profile pulse width
AVG = 4              # FIFO averaging -> 25 Hz effective
RANGE = 4096

MEAS = {"finger_normal mean_ir": 195318, "finger_normal AC span": 326,
        "finger_offset mean_ir": 49672, "nofinger_desk mean_ir": 826,
        "nofinger_room mean_ir": 246}

def counts_to_amps(c, rng=RANGE):
    return c * LSB[rng]

def noise_counts(iph, rng=RANGE, avg=AVG):
    bw = 1 / (2 * PW)
    shot = math.sqrt(2 * q * iph * bw)
    quant = LSB[rng] / math.sqrt(12)
    return math.sqrt(shot ** 2 + quant ** 2) / LSB[rng] / math.sqrt(avg)

if __name__ == "__main__":
    for k, v in MEAS.items():
        print(f"{k:26} {v:>7} counts = {counts_to_amps(v)*1e9:>9.3f} nA "
              f"({100*v/FS_COUNTS:>5.1f}% FS)")
    iph = counts_to_amps(MEAS["finger_normal mean_ir"])
    nf = noise_counts(iph)
    ac = MEAS["finger_normal AC span"]
    print(f"\nnoise floor {nf:.2f} counts rms; cardiac AC {ac} counts; "
          f"SNR {ac/nf:.0f}x ({20*math.log10(ac/nf):.0f} dB)")
    print("\nADC range choice (SNR is range-independent; headroom and the kernel's floor are not):")
    for rng in (2048, 4096, 8192):
        c = iph / LSB[rng]
        peak = (ac / 2) * (LSB[RANGE] / LSB[rng])
        note = "CLIPS" if c >= FS_COUNTS else f"{100*c/FS_COUNTS:.0f}% FS"
        print(f"  {rng:>5} nA: {note:>7}, tired-finger peak {peak*97/326:.0f} counts "
              f"vs the vendor kernel's n_th1 floor of 30")
