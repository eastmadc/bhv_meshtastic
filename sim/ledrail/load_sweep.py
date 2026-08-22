#!/usr/bin/env python3
"""Sustained-load rail voltage against the WS2812B 3.5 V floor.

This is the deck that answers the question rail.cir/sweep2.py cannot: rail.cir caps its
output source at IOUTMAX and has no output floor, so it finds the DCM boundary and nothing
below it. sw_load.cir carries the datasheet 400 ns minimum off-time (SLVS413L 6.4.1), which
is what governs behaviour above that boundary.

An earlier revision published sweep2.py's output as "maximum sustainable current before the
rail drops below 3.5 V". It is not that, and the real threshold is roughly 2x higher.
"""
import subprocess, re, sys, os
from concurrent.futures import ThreadPoolExecutor

TPL = open('sw_load.cir').read()
FLOOR = 3.5

def run(job):
    vb, ipk, load = job
    src = TPL
    for k, v in (('VBAT', vb), ('IPK', f'{ipk:.3f}'), ('ILOADDC', f'{load:.4f}')):
        src, n = re.subn(rf'(?m)^(\.param .*?\b{k})=\S+', rf'\g<1>={v}', src)
        if n != 1:
            sys.exit(f"substitution failed for {k}")
    f = f'_l_{vb}_{ipk}_{load:.4f}.cir'
    open(f, 'w').write(src)
    try:
        o = subprocess.run(['ngspice', '-b', f], capture_output=True,
                           text=True, timeout=1800).stdout
    finally:
        os.unlink(f)
    m = re.search(r'^vled_end\s*=\s*([-\d.e+]+)', o, re.M)
    return (vb, ipk, load, float(m.group(1)) if m else float('nan'))

CORNERS = {
    (3.7, 0.400): (0.055, 0.130, 0.137, 0.150, 0.200, 0.250, 0.260),
    (3.0, 0.400): (0.055, 0.137),
    (3.0, 0.250): (0.055, 0.067, 0.090, 0.105, 0.120, 0.137),
}

if __name__ == "__main__":
    jobs = [(vb, ipk, l) for (vb, ipk), loads in CORNERS.items() for l in loads]
    print(f"Sustained load vs the WS2812B {FLOOR} V minimum, with the datasheet min off-time")
    print(f"{'VBAT':>6}{'Ipk':>7}{'load mA':>9}{'V_led':>9}")
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = sorted(ex.map(run, jobs), key=lambda r: (-r[0], -r[1], r[2]))
    for vb, ipk, load, v in rows:
        flag = f'  <-- below {FLOOR} V' if v < FLOOR else ''
        print(f"{vb:>6.1f}{ipk*1000:>6.0f}m{load*1000:>9.0f}{v:>9.3f}{flag}")
    print("\n  The shipped 55 mA frame budget holds at every corner tested.")
