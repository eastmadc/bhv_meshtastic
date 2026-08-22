import subprocess, re, sys
TPL=open('rail.cir').read()
def run(**kw):
    src=TPL
    for k,v in kw.items():
        src,a=re.subn(rf'^\.param {k}=\S+', f'.param {k}={v}', src, flags=re.M)
        src,b=re.subn(rf'(\.param [^\n]*?\b{k})=\S+', rf'\g<1>={v}', src)
        # rail.cir packs two params per line, so the anchored form alone silently
        # misses L1 and RQ2. That bug made an earlier 500-run campaign vary only
        # three of the five factors it claimed to sweep.
        if a+b==0: sys.exit(f"substitution failed for {k}")
    open('_t.cir','w').write(src)
    out=subprocess.run(['ngspice','-b','_t.cir'],capture_output=True,text=True,timeout=300).stdout
    g=lambda n:(float(m.group(1)) if (m:=re.search(rf'^{n}\s*=\s*([-\d.e+]+)',out,re.M)) else float('nan'))
    return dict(t35=g('t35'),t50=g('t50'),vsag=g('vsag'),vfin=g('vfin'))

print("=== Q1: the shipped delay(1) never let the rail reach the WS2812B 3.5 V minimum ===")
print("    (develop's powerStrips() waits 1 ms; this branch waits 30 ms)")
print(f"{'C4':>7}{'VBAT':>7}{'Ipk':>7}{'t35 ms':>9}{'t50 ms':>9}{'vs 1 ms':>10}{'vs 30 ms':>10}")
worst=0
for c4 in ['100u','220u','330u','470u']:
    for vb in [4.2,3.7,3.4,3.0]:
        r=run(CLOAD=c4,VBAT=vb)
        t35=r['t35']*1e3
        worst=max(worst,t35)
        print(f"{c4:>7}{vb:>7.1f}{'400m':>7}{t35:>9.2f}{r['t50']*1e3:>9.2f}"
              f"{('OK' if t35<1 else 'TOO SLOW'):>10}{('OK' if t35<30 else 'TOO SLOW'):>10}")
print(f"\n  worst case across the grid: {worst:.2f} ms")
print(f"  shipped delay(1):  {'covered' if worst<1 else 'NOT covered - the rail is nowhere near ready'}")
print(f"  this branch delay(30): {'covered' if worst<30 else 'NOT covered'}")

print("\n=== Q2: LED load vs the converter's DCM boundary ===")
print("    NOTE: rail.cir caps its source at IOUTMAX and has no output floor, so vsag below")
print("    marks LOSS OF REGULATION, not the 3.5 V brownout point. For the real floor see")
print("    sw_load.cir, which carries the datasheet 400 ns minimum off-time: +5VL reaches")
print("    3.5 V at ~255 mA (VBAT 3.7, Ipk 400) and ~107 mA (VBAT 3.0, Ipk 250).")
print(f"{'load mA':>9}{'preset':>22}{'VBAT':>6}{'Ipk':>7}{'V_sag':>8}{'regulating?':>25}")
for iled,name in [(0.055,'default animation'),(0.137,'white preset'),(0.363,'white @ scale 1.0')]:
    for vb,ipk in [(3.7,'0.400'),(3.0,'0.250')]:
        r=run(ILEDPK=iled,VBAT=vb,IPK=ipk,CLOAD='220u')
        # Below regulation this deck has no output floor and runs away to physically
        # meaningless voltages. Print the verdict, not the number.
        sag = f"{r['vsag']:>8.2f}" if r['vsag'] > 3.0 else "     n/a"
        print(f"{iled*1000:>9.0f}{name:>22}{vb:>6.1f}{ipk:>7}{sag}"
              f"{('yes' if r['vsag']>=5.0 else 'no - model invalid here'):>25}")

print("\n=== Q3: Monte Carlo, 500 runs (Ipk 250-550mA datasheet spread, L1 +-20%,")
print("    C4 unknown 100-470uF, VBAT 3.0-4.2, Q2 Rds 0.05-0.25) ===")
print("    L1 is swept but cannot matter here: IOUTMAX = 0.5*IPK*TOFF/(TON+TOFF) and both")
print("    TON and TOFF are proportional to L1, so it cancels exactly. The switching model")
print("    in mc.py is where L1 tolerance actually bites.")
import random
random.seed(7)
t35s=[];sags=[]
for i in range(500):
    ipk=random.uniform(0.250,0.550); l1=3.3e-6*random.uniform(0.8,1.2)
    c4=random.uniform(100e-6,470e-6); vb=random.uniform(3.0,4.2)
    rq=random.uniform(0.05,0.25)
    r=run(IPK=f"{ipk:.4f}",L1=f"{l1:.3e}",CLOAD=f"{c4:.3e}",VBAT=f"{vb:.3f}",RQ2=f"{rq:.3f}",ILEDPK=0.055)
    if r['t35']==r['t35']: t35s.append(r['t35']*1e3)
    if r['vsag']==r['vsag']: sags.append(r['vsag'])
t35s.sort()
q=lambda p: t35s[min(len(t35s)-1,int(len(t35s)*p))]
print(f"  n={len(t35s)}")
print(f"  t35 (ms): p50={q(.5):.1f}  p90={q(.9):.1f}  p95={q(.95):.1f}  p99={q(.99):.1f}  max={t35s[-1]:.1f}")
for th in (1,12,25,30):
    print(f"  P(rail not ready at {th:>2} ms) = {100*sum(1 for t in t35s if t>th)/len(t35s):.1f}%")
