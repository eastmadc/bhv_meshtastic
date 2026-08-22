#!/usr/bin/env python3
"""MAX30102 photocurrent and noise budget: the datasheet prediction, then the measurement.

The shot-noise prediction here was wrong by ~27x. It is kept because the correction is the
point, but everything downstream now uses the MEASURED floor. An earlier version of this
file computed only the prediction, which meant the repo's one executable still printed a
number its own README retracted.

Device constants confirmed against the vendor library's datasheet quotes:
  ADC LSB   7.81 / 15.63 / 31.25 / 62.5 pA for the 2048/4096/8192/16384 nA ranges
  LED step  0.2 mA per code   (0x7F -> 25.4 mA and 0xFF -> 51 mA both check out)
  ADC       18-bit  (the driver masks samples with 0x3FFFF)
Measured counts come from hardware captures in docs/pulse-ox/.
"""
import math
q = 1.602176634e-19
LSB = {2048: 7.81e-12, 4096: 15.63e-12, 8192: 31.25e-12, 16384: 62.5e-12}
FS_COUNTS = 2 ** 18
PW = 411e-6          # active-profile pulse width
AVG = 4              # FIFO averaging -> 25 Hz effective
RANGE = 4096

MEAS = {"finger_normal mean_ir": 195318, "finger_normal AC span": 326,
        "finger_offset mean_ir": 49672, "nofinger_desk mean_ir": 826,
        "nofinger_room mean_ir": 246}

# Measured noise floor, no finger, so no cardiac component: window sd IS the floor.
# Sweeping ADC range at fixed drive separates input-referred from output-referred noise.
RANGE_SWEEP = {2048: 6.57, 4096: 4.01, 8192: 2.28, 16384: 1.61}   # counts rms
# Sweeping LED drive at fixed range: flat => not shot-limited.
DRIVE_SWEEP = [(0x00, 0.0, 43, 3.95), (0x2F, 9.4, 648, 4.09), (0x7F, 25.4, 1793, 4.66)]


def counts_to_amps(c, rng=RANGE):
    return c * LSB[rng]


def shot_plus_quant_counts(iph, rng=RANGE, avg=AVG):
    """The ORIGINAL prediction. Retained to show the size of the error."""
    bw = 1 / (2 * PW)
    shot = math.sqrt(2 * q * iph * bw)
    quant = LSB[rng] / math.sqrt(12)
    return math.sqrt(shot ** 2 + quant ** 2) / LSB[rng] / math.sqrt(avg)


def fit_readout():
    """Fit sd^2 = (A/LSB)^2 + B^2 over the range sweep. Returns (A pA, B counts, worst residual)."""
    best = None
    for ai in range(200, 1200):          # A in units of 0.1 pA
        A = ai * 0.1e-12
        for bi in range(0, 400):         # B in units of 0.01 counts
            B = bi * 0.01
            ss = 0.0
            for rng, sd in RANGE_SWEEP.items():
                pred = math.sqrt((A / LSB[rng]) ** 2 + B ** 2)
                ss += (pred - sd) ** 2
            if best is None or ss < best[0]:
                best = (ss, A, B)
    _, A, B = best
    resid = {rng: math.sqrt((A / LSB[rng]) ** 2 + B ** 2) - sd
             for rng, sd in RANGE_SWEEP.items()}
    return A, B, resid


if __name__ == "__main__":
    for k, v in MEAS.items():
        print(f"{k:26} {v:>7} counts = {counts_to_amps(v)*1e9:>9.3f} nA "
              f"({100*v/FS_COUNTS:>5.1f}% FS)")

    iph = counts_to_amps(MEAS["finger_normal mean_ir"])
    ac_pp = MEAS["finger_normal AC span"]

    print("\n--- the prediction that was wrong ---")
    pred = shot_plus_quant_counts(iph)
    print(f"  shot+quantisation floor {pred:.2f} counts rms -> SNR {ac_pp/pred:.0f}x "
          f"({20*math.log10(ac_pp/pred):.0f} dB)   [RETRACTED]")

    print("\n--- measured: LED drive sweep at range 4096 (flat => not shot-limited) ---")
    print(f"  {'code':>6}{'mA':>7}{'mean_ir':>9}{'sd meas':>9}{'shot pred':>11}")
    for code, ma, mean_ir, sd in DRIVE_SWEEP:
        sp = shot_plus_quant_counts(counts_to_amps(mean_ir))
        print(f"  0x{code:02X}{ma:>7.1f}{mean_ir:>9}{sd:>9.2f}{sp:>11.2f}")
    print("  shot noise scales as sqrt(I); this does not move over a 16x change, and is")
    print("  3.95 counts with the LED off entirely. The floor is readout noise.")

    A, B, resid = fit_readout()
    worst = max(abs(v) for v in resid.values())
    print(f"\n--- fit sd^2 = (A/LSB)^2 + B^2 over the range sweep ---")
    print(f"  A = {A*1e12:.1f} pA input-referred, B = {B:.2f} counts output-referred")
    print(f"  {'range':>7}{'sd meas':>9}{'sd fit':>8}{'resid':>8}")
    for rng in sorted(RANGE_SWEEP):
        pf = math.sqrt((A / LSB[rng]) ** 2 + B ** 2)
        print(f"  {rng:>7}{RANGE_SWEEP[rng]:>9.2f}{pf:>8.2f}{resid[rng]:>+8.2f}")
    print(f"  worst residual {worst:.2f} counts. This is a 2-parameter fit to 4 points and")
    print(f"  the 4096 row is the one it fits worst - treat A and B as indicative, not exact.")

    floor = RANGE_SWEEP[RANGE]
    total = math.sqrt(floor ** 2 + shot_plus_quant_counts(iph) ** 2)
    print(f"\n--- corrected SNR at range {RANGE} ---")
    print(f"  measured floor {floor:.2f} counts, shot {shot_plus_quant_counts(iph):.2f} counts,")
    print(f"  in quadrature {total:.2f} counts rms")
    print(f"  cardiac AC {ac_pp} counts PEAK-TO-PEAK -> ratio {ac_pp/total:.0f}x")
    ac_rms = ac_pp / (2 * math.sqrt(2))
    print(f"  as a like-for-like rms SNR (sinusoid, {ac_rms:.0f} counts rms) -> {ac_rms/total:.0f}x "
          f"({20*math.log10(ac_rms/total):.0f} dB)")
    print(f"  the {ac_pp/total:.0f}x figure quoted elsewhere is peak-to-peak signal over rms noise;")
    print(f"  both are stated here because they differ by 2*sqrt(2) and are easy to conflate.")

    print(f"\n--- ADC range choice, using the measured floor ---")
    print(f"  {'range':>7}{'eff noise pA':>14}{'rel SNR':>9}{'occupancy with a finger':>26}")
    eff4096 = math.sqrt(A ** 2 + (B * LSB[4096]) ** 2)
    for rng in (2048, 4096, 8192):
        eff = math.sqrt(A ** 2 + (B * LSB[rng]) ** 2)
        c = iph / LSB[rng]
        note = "CLIPS" if c >= FS_COUNTS else f"{100*c/FS_COUNTS:.0f}% FS"
        print(f"  {rng:>7}{eff*1e12:>14.1f}{eff4096/eff:>9.2f}{note:>26}")
    print("  A finer range gives better SNR, opposite to the 'coarser buys headroom' intuition,")
    print("  but 2048 clips outright with a finger. 4096 is the best available choice.")
