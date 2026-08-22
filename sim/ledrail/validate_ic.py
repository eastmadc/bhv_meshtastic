import subprocess,re,random,os,json,tempfile
def run(seed, base_file):
    BASE=open(base_file).read(); r=random.Random(seed)
    p=dict(VBAT=round(r.uniform(3.0,4.2),3),IPK=round(r.uniform(0.250,0.550),4),
           CLOAD=f"{r.uniform(100e-6,470e-6):.4e}",ESR4=round(r.uniform(0.05,0.50),3),
           LDCR=round(r.uniform(0.07,0.13),3),ILEDPK=round(r.uniform(0.014,0.055),4))
    s=BASE
    for k,v in p.items():
        s=re.sub(rf'^\.param {k}=\S+',f'.param {k}={v}',s,flags=re.M)
        s=re.sub(rf'(\.param [^\n]*?\b{k})=\S+',rf'\g<1>={v}',s)
    s=s.replace('L1   en_in lxa {3.3u}',f'L1   en_in lxa {3.3e-6*r.uniform(0.8,1.2):.4e}')
    fd,path=tempfile.mkstemp(suffix='.cir'); os.close(fd); open(path,'w').write(s)
    try: o=subprocess.run(['ngspice','-b',path],capture_output=True,text=True,timeout=900).stdout
    except subprocess.TimeoutExpired: os.unlink(path); return None
    os.unlink(path)
    g=lambda n:(float(m.group(1)) if (m:=re.search(rf'^{n}\s*=\s*([-\d.e+]+)',o,re.M)) else None)
    return dict(vpp=g('vout_pp'),ilpk=g('il_peak'),vavg=g('vout_avg'),vledmin=g('vled_min'))
# do the ICs change the measured steady state on seeds that converged BOTH ways?
print("Control: same seeds run with and without steady-state ICs")
print(f"{'seed':>6}{'ripple mV (uic / ic)':>26}{'IL pk mA (uic / ic)':>24}{'Vout V (uic / ic)':>22}")
from concurrent.futures import ProcessPoolExecutor
seeds=[3,11,29,44]
with ProcessPoolExecutor(max_workers=8) as ex:
    a=list(ex.map(run,seeds,['sw_mc.cir']*len(seeds)))
    b=list(ex.map(run,seeds,['sw_ic.cir']*len(seeds)))
for s,x,y in zip(seeds,a,b):
    if not x or not y or x['vpp'] is None or y['vpp'] is None: print(f"{s:>6}   (incomplete)"); continue
    print(f"{s:>6}{x['vpp']*1e3:>13.1f} /{y['vpp']*1e3:>10.1f}"
          f"{x['ilpk']*1e3:>14.0f} /{y['ilpk']*1e3:>8.0f}"
          f"{x['vavg']:>13.3f} /{y['vavg']:>8.3f}")
