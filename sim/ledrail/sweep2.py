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
print("Load current at which the converter leaves DCM and loses regulation.")
print("NOT the 3.5 V brownout point: rail.cir caps its source at IOUTMAX and has no output")
print("floor, so it cannot find one. See sw_load.cir for the real floor (~255 mA at VBAT 3.7,")
print("~107 mA at VBAT 3.0 / Ipk 250).")
print(f"{'VBAT':>6}{'Ipk':>8}{'reg limit mA':>14}{'vs default 55mA':>18}")
for vb in [4.2,3.7,3.4,3.0]:
    for ipk in [0.550,0.400,0.250]:
        lo,hi=0.005,0.400
        for _ in range(14):
            mid=(lo+hi)/2
            if run(ILEDPK=f"{mid:.4f}",VBAT=vb,IPK=f"{ipk:.3f}",CLOAD='220u')>=3.5: lo=mid
            else: hi=mid
        tag='' if lo>0.055 else '  <-- BELOW DEFAULT LOAD'
        print(f"{vb:>6.1f}{ipk*1000:>7.0f}m{lo*1000:>14.0f}{lo/0.055:>17.2f}x{tag}")
