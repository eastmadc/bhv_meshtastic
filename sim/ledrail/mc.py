#!/usr/bin/env python3
"""Monte Carlo on the CYCLE-ACCURATE switching model. Parallel, incremental."""
import subprocess, re, random, os, json, tempfile
from concurrent.futures import ProcessPoolExecutor
BASE = open('sw_mc.cir').read()
OUT = 'mc_results.jsonl'

def one(seed):
    r = random.Random(seed)
    p = dict(VBAT=round(r.uniform(3.0, 4.2), 3),
             IPK=round(r.uniform(0.250, 0.550), 4),
             CLOAD=f"{r.uniform(100e-6, 470e-6):.4e}",
             ESR4=round(r.uniform(0.05, 0.50), 3),
             LDCR=round(r.uniform(0.07, 0.13), 3),
             ILEDPK=round(r.uniform(0.014, 0.055), 4))
    s = BASE
    for k, v in p.items():
        s = re.sub(rf'^\.param {k}=\S+', f'.param {k}={v}', s, flags=re.M)
        s = re.sub(rf'(\.param [^\n]*?\b{k})=\S+', rf'\g<1>={v}', s)
    # L1 tolerance
    s = s.replace('L1   en_in lxa {3.3u}', f'L1   en_in lxa {3.3e-6*r.uniform(0.8,1.2):.4e}')
    fd, path = tempfile.mkstemp(suffix='.cir'); os.close(fd)
    open(path, 'w').write(s)
    try:
        o = subprocess.run(['ngspice', '-b', path], capture_output=True, text=True, timeout=900).stdout
    except subprocess.TimeoutExpired:
        os.unlink(path); return dict(seed=seed, ok=False, **p)
    os.unlink(path)
    g = lambda n: (float(m.group(1)) if (m := re.search(rf'^{n}\s*=\s*([-\d.e+]+)', o, re.M)) else None)
    res = dict(seed=seed, ok=True, vavg=g('vout_avg'), vpp=g('vout_pp'),
               ilpk=g('il_peak'), vledmin=g('vled_min'), duty=g('nsw'), **p)
    if res['vavg'] is None: res['ok'] = False
    return res

if __name__ == '__main__':
    N = 250
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT):
            try: done.add(json.loads(line)['seed'])
            except Exception: pass
    todo = [s for s in range(N) if s not in done]
    with ProcessPoolExecutor(max_workers=11) as ex, open(OUT, 'a', buffering=1) as f:
        for res in ex.map(one, todo):
            f.write(json.dumps(res) + '\n')
    print('done', len(todo))
