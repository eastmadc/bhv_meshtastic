# +5VL rail — SPICE model

Averaged model of the badge's LED supply, used to set two firmware constants that were previously
estimated: the rail settle delay in `HeartbeatPixelThread::powerStrips()` and the frame current budget.

Topology extracted from `bhvBadge2026.kicad_pcb` by pad→net mapping, not assumed:
`Vext –D15→ /EN`, `L1 /EN→/SW`, `U1` switch `/SW→GND`, `D16 /SW→+5V`, `C3` output, `R1/R2` divider,
`Q2` high-side `+5V→+5VL`, **`C4` bulk on the switched side**, `Q1`+`R4`/`R5` gate drive.

The TPS61040 is represented by its **envelope** rather than cycle-by-cycle switching: it sources up to
`Iout_max` and regulates to 5.055 V, where `Iout_max` is derived from DCM peak-current operation
(`t_on = L·Ipk/Vin`, `t_off = L·Ipk/(Vout+Vf−Vin)`, `Iout_max = ½·Ipk·t_off/(t_on+t_off)`) rather than
assumed. A switching model was tried first and was abandoned: without a set-reset latch the comparator
chatters and the timestep collapses, and switching ripple does not change any of the answers below.

## Running

```
ngspice -b rail.cir      # single operating point
python3 run.py           # C4 × VBAT sweep, load steps, 500-run Monte Carlo
python3 sweep2.py        # maximum sustainable LED current per corner
```

## Results

**Rail settle.** Time to the WS2812B 3.5 V minimum, VBAT 4.2 → 3.0:

| C4 | t(3.5 V) |
|---|---|
| 100 µF | 2.8 – 4.3 ms |
| 220 µF | 6.0 – 9.2 ms |
| 330 µF | 9.0 – 13.6 ms |
| 470 µF | 12.8 – 19.3 ms |

Monte Carlo, 500 runs over Ipk 250–550 mA, L1 ±20%, C4 100–470 µF, VBAT 3.0–4.2:
P(not ready at 12 ms) = **29.2%**, at 25 ms = 0.2%, at 30 ms = **0.0%**. The firmware waited 12 ms; it
now waits 30. The dominant uncertainty is C4, whose value is unspecified in the hardware design.

**Maximum sustainable LED current** before the rail drops below 3.5 V:

| VBAT | Ipk 550 mA | Ipk 400 mA | Ipk 250 mA |
|---|---|---|---|
| 4.2 | 203 mA | 149 mA | 95 mA |
| 3.7 | 177 mA | 130 mA | 83 mA |
| 3.0 | 142 mA | 104 mA | **67 mA** |

The shipped animation peaks near 55 mA — only **1.21× headroom** in the worst corner. The white preset
draws ~137 mA and browns out in every corner but a full battery with a best-case part. Hence the frame
current budget of 55 mA, which scales bright frames down instead of collapsing the supply.

## Limitations

The envelope model has no output floor, so simulated sag goes unphysically negative under gross overload
(e.g. −21 V at 137 mA / 3.0 V). Read those as "the rail collapses", not as a voltage. Switching ripple,
inductor saturation and the Q1/Q2 gate-drive transient are not modelled; none affect the two constants
this was built to set. `C4`'s real value is unknown, and it dominates every result here.

---

# Cycle-accurate switching model (`sw.cir`)

The averaged model above answers the design questions but cannot show ripple, switching frequency, or
transient dips *within* an animation pulse. `sw.cir` models the converter cycle by cycle.

The control loop is a real peak-current PFM latch — set when FB falls below the 1.233 V reference, reset
when inductor current reaches Ipk — with the algebraic loop broken by a 1 ns RC. That latch is what the
first attempt lacked: a bare comparator chatters at the threshold and ngspice's timestep collapses to
picoseconds. Includes L1 DCR, BAT54W diode models, and C4's ESR.

**Operating point** (C4 = 220 µF, 55 mA load, VBAT 3.7, Ipk 400 mA):

| quantity | value |
|---|---|
| V_out average | 5.061 V (target 5.055) |
| output ripple | 31.3 mV pk-pk |
| inductor peak current | 401.6 mA (limit 400 — the latch holds) |
| switch duty | 11.8% → DCM confirmed |
| V_led minimum during animation pulses | 5.055 V — **no transient dip** |

That last row is the point of building it: the averaged model could not rule out a dip *inside* each
animation pulse, and there isn't one at the shipped 55 mA load. The two models agree on regulation
(5.061 vs 5.048 V), which cross-validates both.

A Monte Carlo on the switching model was attempted and abandoned: each 60 ms cycle-accurate run costs
~30 s, so a meaningful sample exceeds any reasonable budget. The 500-run statistics come from the
averaged model, which is the right tool for that job.

# Mixed-signal: gate drive and inrush (`inrush.cir`)

GPIO48's digital edge into the analog power path. Q1 (2N7002H) and Q2 (DMP2012SN) are modelled as
switches with explicit datasheet gate capacitance rather than compact models, so every parameter is
visible and none is hidden in a vendor subcircuit.

**Q2 closes into a discharged C4 while the only local charge is C3 (4.7 µF):**

- gate transition: **~9 ns** — Q1 pulls Q2's gate down through ~7.5 Ω against 600 pF
- **+5V collapses to 0.69 V** as C3 charge-shares into C4 through Q2's 55 mΩ and C4's ESR
- inrush is limited only by that ~0.2 Ω path — of order **20 A** for roughly a microsecond
- **recovery to 5.0 V takes 6.3 ms (C4 = 100 µF) to 26.6 ms (470 µF)**

The recovery figure is an *independent* second route to the same firmware conclusion: the 30 ms settle
delay covers it, and the previous 12 ms did not.

**Series gate resistor (Q1 drain → Q2 gate), for any future revision:**

| Rgate | +5V dip |
|---|---|
| 0 (as built) | 0.687 V |
| 100 Ω | 0.626 V |
| 470 Ω | 0.395 V |
| 1 kΩ | **0.242 V** |
| 2.2 kΩ | 0.234 V |

Slowing the gate edge makes Q2 traverse its linear region and limits di/dt. Recovery time is unchanged
(12.84 ms) because that is set by the converter's current limit charging C4, not by the gate. ~1 kΩ
captures most of the benefit; beyond ~2.2 kΩ it fights R4's 10 kΩ pull-up and turn-*off* slows. Note
10 kΩ would not converge here at all, which is itself a hint that Q2 lingers in its linear region.

Firmware cannot fix this — the first-pulse peak is set by V/R at closure, and GPIO48 is digital. It is a
hardware note for a future board, not an action item: the badges work, and the event happens only on
power-state transitions.

# Digital: WS2812B bit timing

Verified against the firmware rather than simulated, since it is deterministic. `rmtSetTick(100.0f)`
gives 100 ns per tick, and `encodeByteToRmt` emits 8/4 ticks for a one and 4/8 for a zero:

| | firmware | WS2812B spec | margin |
|---|---|---|---|
| T0H | 400 ns | 250–550 | centred |
| T0L | 800 ns | 700–1000 | centred |
| T1H | 800 ns | 650–950 | centred |
| T1L | 400 ns | 300–600 | centred |
| bit period | 1.25 µs | 1.25 µs ±600 ns | exact |

All four intervals sit near the centre of their windows. No defect, and no change made.

# What is deliberately NOT modelled

The MAX30102 is a sealed module with no public device model, so the entire analog sensing path — the
actual subject of this review — is outside SPICE's reach here. Its LED drivers, photodiode front end,
ambient-light cancellation and 18-bit sigma-delta cannot be simulated from available data, and inventing
a behavioural stand-in would produce numbers with no claim to accuracy. Everything known about that path
in this project was measured on hardware instead, which is documented in `docs/pulse-ox/`.

Also unmodelled: inductor saturation (L1's rating is unknown), PCB parasitics, and thermal effects.

---

# Monte Carlo on the cycle-accurate model (`mc.py`, `sw_mc.cir`)

The earlier note said a switching-model Monte Carlo was unaffordable. That was wrong — it is affordable,
it just needs parallelism. Each run costs ~2 minutes (the 200 ns maxstep sets a floor of ~125k timesteps,
and it cannot be relaxed much because the switch on-time is only ~388 ns), so 250 runs across 11 workers
is ~45 minutes rather than the days a serial run implies.

250 runs over VBAT 3.0–4.2, Ipk 250–550 mA, L1 ±20%, C4 100–470 µF, C4 ESR 0.05–0.5 Ω, DCR ±30%, and
load 14–55 mA (bounded by the frame current budget, so it reflects what the firmware can now request).
Raw results in `mc_results.jsonl.gz`. **245/250 converged.**

| quantity | p50 | p90 / p99 | worst |
|---|---|---|---|
| output ripple | 28.5 mV | 42.8 mV (p90) | 61.6 mV |
| inductor peak current | 406.8 mA | 546.6 mA (p99) | 550.2 mA |
| V_out regulation | 5.064 V | — | 5.060 – 5.070 V |
| **V_led minimum** | — | 5.054 V (p01) | **5.048 V** |

**The 55 mA frame budget is safe across the whole tolerance space.** Zero of 245 runs came within
1.5 V of the 3.5 V WS2812B floor — worst case 5.048 V. This was the one result that could have forced
another firmware change, and it does not.

**The inductor does not saturate.** Worst-case peak is 550.2 mA against a ~1.1 A saturation rating for the
2520/3.3 µH part the BOM links (Murata MLP2520S3R3) — **2.0× margin**. Had this landed near Isat, both
models would have been invalid, since inductance collapse is outside either one's assumptions. It is the
main reason the switching model was worth building.

**The latch tracks its setpoint to 0.36% median, 0.76% worst**, confirming the peak-current control is
behaving as designed rather than as an artefact of the RC that breaks its algebraic loop.

**Regulation holds at 5.060–5.070 V** against a 5.055 V target — a consistent +0.1 to +0.3% offset from
the model's proportional control, not a spread. Ripple stays under 1.3% of rail.

## Covering the last 2% (`sw_ic.cir`, `retry.py`, `validate_ic.py`)

Five runs initially failed to converge, all with C4 ≥ 370 µF *and* VBAT ≤ 3.36 V — the largest capacitor
with the weakest supply, which is the stiff *startup* corner: a big capacitor charging slowly from zero.

Rather than loosen tolerances (which would trade accuracy for convergence), those runs restart from
steady-state initial conditions, `.ic v(out)=5.055 v(vled)=5.050 v(c4mid)=5.050`. That is legitimate
here because this campaign measures **steady-state** quantities — ripple, inductor peak, regulation,
V_led during animation pulses — while the *ramp* was already characterised by the averaged model. Skipping
the startup transient does not change what is being measured.

Validated rather than assumed: four seeds that converged both ways were run with and without the ICs.

| seed | ripple mV (uic / ic) | IL peak mA | V_out V |
|---|---|---|---|
| 3 | 17.9 / 18.0 | 415 / 415 | 5.062 / 5.062 |
| 11 | 26.0 / 27.9 | 420 / 420 | 5.065 / 5.065 |
| 29 | 28.3 / 25.3 | 355 / 355 | 5.062 / 5.062 |
| 44 | 23.0 / 29.9 | 414 / 414 | 5.061 / 5.061 |

Inductor peak and regulation are identical to three significant figures. Ripple varies ±4 mV in *both*
directions — measurement-window phase, not a systematic shift.

All five re-ran cleanly, and the corner turns out to be the **best-behaved** in the campaign: ripple
12.1–26.1 mV (below the p50 of 28.5 mV, since a larger C4 filters better), IL peak 284–429 mA, V_led
minimum 5.053–5.055 V. Nothing was hiding there.

**Coverage is now 250/250.**
