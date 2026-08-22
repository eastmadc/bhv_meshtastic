# MAX30102 noise floor — predicted, then measured

The module is sealed and cannot be simulated at transistor level, but its transfer function is specified,
so the noise floor can be predicted from the datasheet. It was, and then it was **measured on hardware** —
which showed the prediction was wrong by a factor of 27 and for a structural reason. Both are kept here,
because the correction is the useful part.

Device constants are confirmed against the vendor library's datasheet quotes: ADC LSB 7.81 / 15.63 / 31.25
/ 62.5 pA for the 2048 / 4096 / 8192 / 16384 nA ranges, LED step 0.2 mA per code, 18-bit conversion.

Run: `python3 noise_budget.py`

## Measured counts are physically sensible

| capture | counts | photocurrent | % of full scale |
|---|---|---|---|
| finger, steady | 195,318 | 3052.8 nA | 74.5% |
| cardiac AC span | 326 | 5.1 nA | 0.1% |
| no finger, LED off | 43 | 0.7 nA | 0.02% |

At 9.4 mA drive the optical return is 3.25 × 10⁻⁴ A/A, a plausible reflective-PPG coupling.

## The prediction, and why it was wrong

Shot noise at 3052.8 nA over a 411 µs integration is 34.5 pA rms = 2.21 counts, and quantisation adds
0.29 counts, giving **1.11 counts rms** after 4× averaging. That implied an SNR of 293× (49 dB) against
the 326-count cardiac AC.

Measured with no finger, so with no cardiac component, the window standard deviation **is** the noise
floor. Sweeping LED drive across a 16× range:

| drive | mA | mean_ir | measured sd | shot-noise prediction |
|---|---|---|---|---|
| 0x00 | 0.0 | 43 | **3.95** | 0.15 |
| 0x2F | 9.4 | 648 | **4.09** | 0.16 |
| 0x7F | 25.4 | 1793 | **4.66** | 0.18 |

**Flat, and ~27× above prediction.** Shot noise scales as √I; this does not move across a 16× change in
photocurrent, and it is still 3.95 counts with the LED completely off. It is **readout noise**, not photon
noise, and it dominates shot noise entirely at these light levels.

## Where the noise actually lives

Sweeping ADC range at fixed drive separates input-referred (analog, fixed pA) from output-referred
(digital, fixed counts):

| range | pA/count | sd (counts) | sd (pA) |
|---|---|---|---|
| 2048 | 7.81 | 6.57 | 51.3 |
| 4096 | 15.63 | 4.01 | 62.6 |
| 8192 | 31.25 | 2.28 | 71.3 |
| 16384 | 62.5 | 1.61 | 100.8 |

Neither is constant, so it is mixed. Least-squares on `sd² = (A/LSB)² + B²` gives **A ≈ 51 pA
input-referred plus B ≈ 1.6 counts output-referred**, worst residual 0.38 counts (at the 4096 row).
That is two parameters fitted to four points, so treat A and B as indicative rather than exact — an
earlier revision quoted A ≈ 50 / B ≈ 1.4 and claimed 0.5-count agreement, which its own numbers missed.

## Corrected SNR, and what still holds

Readout 4.01 counts and shot 1.11 counts in quadrature give **4.16 counts rms**, against a measured
326-count cardiac AC — a ratio of **78×**, not the 293× predicted from shot noise alone.

One caveat on that number, since it is easy to misread: 326 counts is a peak-to-peak span while 4.16 is
rms, so 78× is not a like-for-like SNR. Treating the pulse as a sinusoid gives 115 counts rms and a true
**SNR of 28× (29 dB)**. Both are quoted here because the distinction is a factor of 2√2. The worst session
recorded, a fatigued finger at 97 counts AC, sits at **23×** peak-to-peak-over-rms, i.e. ~8× rms.

**The contact-limited conclusion survives.** 78× is still a large margin, and every signal-quality problem
measured in this project remains mechanical rather than optical or electronic. But the margin is 3.7×
smaller than claimed and the limiting mechanism is different, so the claim is restated rather than
repeated.

## The shipped configuration is the best of the three available

Since `SNR = Iph / sqrt(A² + B²·LSB²)`, a **finer** range gives better SNR — the opposite of the intuition
that a coarser range "buys headroom for free":

| range | effective noise | relative SNR | occupancy with a finger |
|---|---|---|---|
| 2048 nA | 52.6 pA | 1.08× | **clips** (390,886 > 262,143) |
| **4096 nA** | 56.7 pA | **1.00×** | 75% FS |
| 8192 nA | 70.7 pA | 0.80× | 37% FS |

8192 nA costs **20% of SNR** on top of pushing a fatigued finger below the vendor kernel's hard 30-count
peak floor. 2048 nA would be 8% better and clips outright. **4096 nA is the best available choice.**
These margins ride on the A/B fit above, so the ranking is solid but the percentages are approximate.

And because the noise floor is flat rather than shot-limited, raising LED current *would* improve SNR
roughly linearly — except that at 0x2F the on-finger DC is already 74.5% of full scale, so any meaningful
increase clips. **The badge is therefore running at the maximum drive its range permits, at the finest
range that does not clip.** That configuration is optimal, and it was chosen before any of this analysis
existed.
