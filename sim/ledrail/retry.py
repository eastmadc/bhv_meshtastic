import subprocess,re,random,os,json,tempfile
BASE=open('sw_ic.cir').read()
seeds=[int(x) for x in open('failed_seeds.txt').read().split()]
def one(seed):
    r=random.Random(seed)
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
    except subprocess.TimeoutExpired: os.unlink(path); return dict(seed=seed,ok=False,**p)
    os.unlink(path)
    g=lambda n:(float(m.group(1)) if (m:=re.search(rf'^{n}\s*=\s*([-\d.e+]+)',o,re.M)) else None)
    return dict(seed=seed,ok=g('vout_avg') is not None,vavg=g('vout_avg'),vpp=g('vout_pp'),
                ilpk=g('il_peak'),vledmin=g('vled_min'),duty=g('nsw'),**p)
from concurrent.futures import ProcessPoolExecutor
with ProcessPoolExecutor(max_workers=5) as ex, open('mc_retry.jsonl','w') as f:
    for res in ex.map(one,seeds):
        f.write(json.dumps(res)+'\n')
        print(f"  seed {res['seed']}: {'OK' if res['ok'] else 'FAIL'}  C4={res['CLOAD']} VBAT={res['VBAT']}"
              + (f"  vpp={res['vpp']*1e3:.1f}mV ilpk={res['ilpk']*1e3:.0f}mA vledmin={res['vledmin']:.3f}V" if res['ok'] else ""))
