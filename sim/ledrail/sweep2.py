import subprocess,re
TPL=open('rail.cir').read()
def run(**kw):
    src=TPL
    for k,v in kw.items():
        src=re.sub(rf'^\.param {k}=\S+', f'.param {k}={v}', src, flags=re.M)
        src=re.sub(rf'\.param {k}=\{{[^}}]*\}}', f'.param {k}={v}', src)
    open('_s.cir','w').write(src)
    o=subprocess.run(['ngspice','-b','_s.cir'],capture_output=True,text=True,timeout=180).stdout
    m=re.search(r'^vsag\s*=\s*([-\d.e+]+)',o,re.M)
    return float(m.group(1)) if m else float('nan')
print("Maximum sustainable LED current before the rail drops below the WS2812B 3.5 V minimum")
print(f"{'VBAT':>6}{'Ipk':>8}{'max safe mA':>13}{'headroom vs default 55mA':>26}")
for vb in [4.2,3.7,3.4,3.0]:
    for ipk in [0.550,0.400,0.250]:
        lo,hi=0.005,0.400
        for _ in range(14):
            mid=(lo+hi)/2
            if run(ILEDPK=f"{mid:.4f}",VBAT=vb,IPK=f"{ipk:.3f}",CLOAD='220u')>=3.5: lo=mid
            else: hi=mid
        tag='' if lo>0.055 else '  <-- BELOW DEFAULT LOAD'
        print(f"{vb:>6.1f}{ipk*1000:>7.0f}m{lo*1000:>13.0f}{lo/0.055:>21.2f}x{tag}")
