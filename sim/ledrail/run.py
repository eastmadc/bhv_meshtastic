import subprocess, re, itertools, sys, os
TPL=open('rail.cir').read()
def run(**kw):
    src=TPL
    for k,v in kw.items():
        src=re.sub(rf'^\.param {k}=\S+', f'.param {k}={v}', src, flags=re.M)
        src=re.sub(rf'\.param {k}=\{{[^}}]*\}}', f'.param {k}={v}', src)
    open('_t.cir','w').write(src)
    out=subprocess.run(['ngspice','-b','_t.cir'],capture_output=True,text=True,timeout=180).stdout
    g=lambda n:(float(m.group(1)) if (m:=re.search(rf'^{n}\s*=\s*([-\d.e+]+)',out,re.M)) else float('nan'))
    return dict(t35=g('t35'),t50=g('t50'),vsag=g('vsag'),vfin=g('vfin'))

print("=== Q1: is the firmware's delay(12) enough for the rail to reach the WS2812B 3.5 V minimum? ===")
print(f"{'C4':>7}{'VBAT':>7}{'Ipk':>7}{'t35 ms':>9}{'t50 ms':>9}{'verdict vs delay(12)':>24}")
worst=0
for c4 in ['100u','220u','330u','470u']:
    for vb in [4.2,3.7,3.4,3.0]:
        r=run(CLOAD=c4,VBAT=vb)
        t35=r['t35']*1e3
        worst=max(worst,t35)
        v='OK' if t35<12 else f'TOO SLOW by {t35-12:.1f} ms'
        print(f"{c4:>7}{vb:>7.1f}{'400m':>7}{t35:>9.2f}{r['t50']*1e3:>9.2f}{v:>24}")
print(f"\n  worst case across the grid: {worst:.2f} ms  (firmware waits 12 ms)")

print("\n=== Q2: does the LED load collapse the rail? (WS2812B needs >=3.5 V) ===")
print(f"{'load mA':>9}{'preset':>22}{'VBAT':>6}{'Ipk':>7}{'V_sag':>8}{'verdict':>12}")
for iled,name in [(0.055,'default animation'),(0.137,'white preset'),(0.363,'white @ scale 1.0')]:
    for vb,ipk in [(3.7,'0.400'),(3.0,'0.250')]:
        r=run(ILEDPK=iled,VBAT=vb,IPK=ipk,CLOAD='220u')
        ok='OK' if r['vsag']>=3.5 else 'BROWNOUT'
        print(f"{iled*1000:>9.0f}{name:>22}{vb:>6.1f}{ipk:>7}{r['vsag']:>8.2f}{ok:>12}")

print("\n=== Q3: Monte Carlo, 500 runs (Ipk 250-550mA datasheet spread, L1 +-20%,")
print("    C4 unknown 100-470uF, VBAT 3.0-4.2, Q2 Rds 0.05-0.25) ===")
import random, statistics as st
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
print(f"  t35 (ms): p50={q(.5):.1f}  p90={q(.9):.1f}  p95={q(.95):.1f}  p99={q(.99):.1f}  max={t35s[-1]:.1f}")
print(f"  P(rail not ready at firmware's 12 ms) = {100*sum(1 for t in t35s if t>12)/len(t35s):.1f}%")
print(f"  P(rail not ready at 25 ms)            = {100*sum(1 for t in t35s if t>25)/len(t35s):.1f}%")
print(f"  P(rail not ready at 30 ms)            = {100*sum(1 for t in t35s if t>30)/len(t35s):.1f}%")
print(f"  brownout at default animation: {100*sum(1 for v in sags if v<3.5)/len(sags):.1f}% of runs")
