#!/usr/bin/env python3
"""Sweep C4 and the battery/current-limit corners for inrush.cir.

The C4 and Rgate tables in README.md were originally produced by hand, with no
driver in the repo. That is how a 2.2x topology error survived to publication.
This regenerates them.
"""
import subprocess, re, sys

TPL = open('inrush.cir').read()

def run(**kw):
    src = TPL
    for k, v in kw.items():
        src, n = re.subn(rf'(?m)^(\.param .*?\b{k})=\S+', rf'\g<1>={v}', src)
        if n == 0:
            sys.exit(f"substitution failed for {k} - check the .param lines")
    open('_i.cir', 'w').write(src)
    o = subprocess.run(['ngspice', '-b', '_i.cir'], capture_output=True,
                       text=True, timeout=900).stdout
    g = lambda n: (lambda m: float(m.group(1)) if m else float('nan'))(
        re.search(rf'^{n}\s*=\s*([-\d.e+]+)', o, re.M))
    return {n: g(n) for n in ('vout_dip', 't_rec', 't_vled35', 'vled_pk')}

EN = 5e-3  # enable edge in the PULSE source

print("Recovery of +5V to 5.0 V after Q2 closes into a discharged C4")
print(f"{'VBAT':>6}{'Ipk':>7}{'C4':>8}{'dip V':>8}{'recovery ms':>13}")
rows = []
for vb, ipk in ((3.7, 0.400), (3.0, 0.250)):
    for c4 in ('100u', '220u', '470u'):
        r = run(CLOAD=c4, VBAT=vb, IPK=f'{ipk:.3f}')
        rec = (r['t_rec'] - EN) * 1e3
        rows.append((vb, ipk, c4, r['vout_dip'], rec))
        print(f"{vb:>6.1f}{ipk*1000:>6.0f}m{c4:>8}{r['vout_dip']:>8.3f}{rec:>13.2f}")

worst = max(rows, key=lambda r: r[4])
print(f"\n  worst case: {worst[4]:.2f} ms at VBAT {worst[0]}, Ipk {worst[1]*1000:.0f} mA, C4 {worst[2]}")
print(f"  firmware waits 30 ms -> {'covered' if worst[4] < 30 else 'NOT COVERED'}")
