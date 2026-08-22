# +5VL rail — SPICE model

Averaged model of the badge's LED supply, used to set two firmware constants that were previously
estimated: the rail settle delay in `HeartbeatPixelThread::powerStrips()` and the frame current budget.

Topology extracted from `bhvBadge2026.kicad_pcb` by pad→net mapping:
`Vext –D15→ /EN`, `L1 /EN→/SW`, `U1` switch `/SW→GND`, `D16 /SW→+5V`, `C3` output, `R1/R2` divider,
`Q2` high-side `+5V→+5VL`, **`C4` bulk on the switched side**, `Q1`+`R4`/`R5` gate drive.

The TPS61040 is represented by its **envelope** rather than cycle-by-cycle switching: it sources up to
`Iout_max` and regulates to 5.055 V, where `Iout_max` is derived from DCM peak-current operation
(`t_on = L·Ipk/Vin`, `t_off = L·Ipk/(Vout+Vf−Vin)`, `Iout_max = ½·Ipk·t_off/(t_on+t_off)`). A switching model was tried first and was abandoned: without a set-reset latch the comparator
chatters and the timestep collapses, and switching ripple does not change any of the answers below.

## Running

```
ngspice -b rail.cir       # single operating point
python3 run.py            # C4 x VBAT sweep, load steps, 500-run Monte Carlo
python3 sweep2.py         # loss-of-regulation current per corner (see caveat below)
python3 inrush_sweep.py   # C4 inrush and recovery, per battery corner
ngspice -b sw_load.cir    # sustained-load rail voltage, with the datasheet min off-time
```

Run with **ngspice-42**; nothing here pins a version, and `.options maxstep` is silently ignored
by this build (verified: 200 ns and 2 ns give byte-identical results and identical runtime), so a
different simulator may not reproduce these timesteps.

## Results

**Rail settle.** Time to the WS2812B 3.5 V minimum, VBAT 4.2 → 3.0:

| C4 | t(3.5 V) |
|---|---|
| 100 µF | 2.8 – 4.3 ms |
| 220 µF | 6.0 – 9.2 ms |
| 330 µF | 9.0 – 13.6 ms |
| 470 µF | 12.8 – 19.3 ms |

Monte Carlo, 500 runs over Ipk 250–550 mA, L1 ±20%, C4 100–470 µF, VBAT 3.0–4.2:
P(not ready at 1 ms) = **100%**, at 12 ms = 29.2%, at 25 ms = 0.2%, at 30 ms = **0.0%**.

`develop`'s `powerStrips()` waits **1 ms** (`HeartbeatPixelThread.cpp`); this branch waits 30. An
earlier revision of this file said the firmware waited 12 ms, which was simply wrong — no such
constant exists on `develop` or on this branch. The real baseline makes the case stronger, not
weaker: the rail is never ready at 1 ms, in any corner.

L1 is swept but cannot matter in this model: `Iout_max = ½·Ipk·t_off/(t_on+t_off)` and both `t_on`
and `t_off` are proportional to L1, so it cancels exactly. Only the switching model (`mc.py`) is
sensitive to L1 tolerance. The dominant uncertainty here is C4, unspecified in the hardware design.

**Loss-of-regulation current** — the load at which the converter leaves DCM:

| VBAT | Ipk 550 mA | Ipk 400 mA | Ipk 250 mA |
|---|---|---|---|
| 4.2 | 203 mA | 149 mA | 95 mA |
| 3.7 | 177 mA | 130 mA | 83 mA |
| 3.0 | 142 mA | 104 mA | **67 mA** |

**This table was previously published under the label "maximum sustainable current before the rail
drops below 3.5 V". That label was false and has been retracted.** `rail.cir` caps its output source
at exactly `Iout_max` and has no output floor, so it cannot compute a 3.5 V threshold — below
regulation it runs away to physically meaningless voltages. What the bisection actually finds is the
DCM boundary, which is TI's own definition of maximum load current (SLVS413L 7.2.2.1), but it is not
a brownout point.

For the real floor, `sw_ctl.cir` / `sw_load.cir` add the datasheet's 400 ns minimum off-time
(SLVS413L 6.4.1) to the cycle-accurate model. Adding it does not perturb the shipped operating point
(V_out 5.0661 V vs 5.0663 V unmodified), which is what makes the rest of the deck trustworthy. With a
sustained DC load, `+5VL` reaches 3.5 V at:

| corner | loss of regulation | **3.5 V brownout** |
|---|---|---|
| VBAT 3.7, Ipk 400 mA | 130 mA | **~255 mA** |
| VBAT 3.0, Ipk 250 mA | 67 mA | **~107 mA** |

So the rail tolerates roughly **2× more** than the first table implies. Measured points:
55 mA → 5.067 V / 4.721 V; 137 mA → 5.030 V / 3.017 V; 250 mA → 3.552 V at the good corner.

The 55 mA frame budget still earns its place — it holds 4.72 V at the worst corner — but it protects
the weak-battery corner, not bright patterns generally.

## Limitations

The envelope model has no output floor, so simulated sag goes unphysically negative under gross overload
(e.g. −21 V at 137 mA / 3.0 V). Read those as "regulation lost", not as a voltage — and **not** as a
brownout, which is the error that produced the retracted table above. `run.py` now prints `n/a` there
rather than a number. Switching ripple, inductor saturation and the Q1/Q2 gate-drive transient are not
modelled; none affect the two constants this was built to set. `C4`'s real value is unknown, and it
dominates every result here.

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
(5.061 vs 5.048 V), but that is **not** independent corroboration: `rail.cir` is handed
`VTARGET=5.055` directly, and `sw.cir`'s 1.233 V × (1 + 620k/200k) is also 5.055 V. They agree because
they were given the same setpoint. The genuinely independent check is the ripple and the absence of a
per-pulse dip, which the averaged model cannot produce at all.

Note the rows above headed "55 mA load": only `V_led minimum` is measured at 55 mA. The other
measurement windows (20–29 ms) close before the animation pulse train starts at 30 ms, so they
describe the 14 mA quiescent load. The `V_led minimum` row is the one that matters, and it is correct.

A Monte Carlo on the switching model was initially thought unaffordable. Measured on this machine, one
25 ms `sw_ic.cir` run costs **~16 s**, and runs with a large C4 and a weak supply cost substantially
more. Earlier revisions of this file quoted both "~30 s" and "~2 minutes" per run; neither was
measured. It is affordable with parallelism — see the campaign at the end.

# Mixed-signal: gate drive and inrush (`inrush.cir`)

GPIO48's digital edge into the analog power path. Q1 (2N7002H) and Q2 (DMP2012SN) are modelled as
switches with explicit datasheet gate capacitance rather than compact models, so the parameters are
visible in the deck.

**Q2 closes into a discharged C4 while the only local charge is C3 (4.7 µF):**

- gate transition: **~9 ns** — Q1 pulls Q2's gate down through ~7.5 Ω against 600 pF
- **+5V collapses to 0.69 V** as C3 charge-shares into C4 through Q2's 55 mΩ and C4's ESR
- inrush is limited only by that ~0.2 Ω path — **26.3 A** peak, matching the analytic 5.055 V / 0.205 Ω
  = 24.7 A; still 9.2 A at 1 µs, and over by 10 µs
- **recovery to 5.0 V** (`inrush_sweep.py`):

| C4 | VBAT 3.7, Ipk 400 mA | VBAT 3.0, Ipk 250 mA |
|---|---|---|
| 100 µF | 2.34 ms | 6.35 ms |
| 220 µF | 5.00 ms | 13.59 ms |
| 470 µF | 10.53 ms | **28.66 ms** |

**These figures replace a published 6.3–26.6 ms, which was wrong.** That deck modelled the boost as a
single current source into the output node — no L1, no D16, no input node — so the rail could only
recharge through an idealised path, and it used a hardcoded 105 mA rather than deriving the envelope
from the battery. It also never swept the battery corner. The corrected deck adds
`Vext → D15 → L1 → D16 → +5V`, which is reverse-biased in regulation and carries nothing, but dominates
when C4 inrush pulls the rail below the input.

The 30 ms settle delay still covers the worst case, but by **1.3 ms**, not the comfortable margin the
old numbers implied. Treat this as a second route to the same conclusion rather than an independent
one: `rail.cir` still carries the same missing-passthrough simplification.

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

Also unmodelled: inductor saturation, PCB parasitics, and thermal effects. L1's saturation rating is
*not* unknown — the BOM links a Murata MLP2520S3R3 at ~1.1 A — it is simply not represented in the
decks; the margin against it is assessed in the campaign below.

---

# Monte Carlo on the cycle-accurate model (`mc.py`, `sw_mc.cir`)

The earlier note said a switching-model Monte Carlo was unaffordable. That was wrong — it is affordable,
it just needs parallelism. Cost is set by the `tran` step (100 ns) against a ~388 ns switch on-time, not
by `.options maxstep`, which **this ngspice build ignores entirely** (200 ns and 2 ns produce identical
output and identical runtime). Runs range from ~16 s to several minutes depending on C4 and supply, so
250 runs across 11 workers is well under an hour.

250 runs over VBAT 3.0–4.2, Ipk 250–550 mA, L1 ±20%, C4 100–470 µF, C4 ESR 0.05–0.5 Ω, DCR ±30%, and
load 14–55 mA (bounded by the frame current budget, so it reflects what the firmware can now request).
Raw results in `mc_results.jsonl.gz`. **245/250 converged.**

| quantity | p50 | p90 / p99 | worst |
|---|---|---|---|
| output ripple | 28.5 mV | 42.8 mV (p90) | 61.6 mV |
| inductor peak current | 406.8 mA | 546.6 mA (p99) | 550.2 mA |
| V_out regulation | 5.064 V | — | 5.060 – 5.070 V |
| **V_led minimum** | — | 5.054 V (p01) | **5.048 V** |

**The 55 mA frame budget survives every run in this campaign**, worst case 5.048 V against the 3.5 V
WS2812B floor. Stated carefully, because "zero of 245 runs came within 1.5 V of the floor" — as an
earlier revision put it — carries no margin information: `V_led minimum` spans only 8.65 mV across all
245 runs and correlates with nothing (R² = 0.058 against all six inputs). It is a cliff, not a slope,
so the campaign shows the design sits far from the edge, not how far.

The campaign also never sampled the corner that matters: the joint stress case (VBAT → 3.0, Ipk → 250,
load → 55 mA) has probability 0.0034 under uniform sampling and was drawn zero times in 250 runs. The
actual evidence for the budget is the deterministic corner run in `sw_load.cir` — 55 mA holds 4.721 V
at VBAT 3.0 / Ipk 250 — not the Monte Carlo. Note also that this campaign's margin statement, the
"1.21×" in the settle section, and the "~4%" in `docs/pulse-ox/hardware-notes.md` are three different
quantities against three different references; only the 3.5 V figures are brownout margins.

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
minimum 5.053–5.055 V.

Worth stating the limit of that control: four paired seeds can only exclude a systematic ripple shift
larger than about ±6.6 mV. The five retried runs are also missing-not-at-random — every failure fell in
a region holding 17 of 250 runs, where the failure rate was 29.4% against 0% elsewhere. Folding the
retries back in moves ripple p50 by −0.03 mV and IL-peak p50 by −0.65 mA, so the bias is real in
principle and immaterial in fact.

**Coverage is now 250/250.**
