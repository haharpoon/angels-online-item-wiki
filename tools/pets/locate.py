import json,csv,re,collections
from pathlib import Path
S=Path('src'); N=json.load(open('build/need.json')); need=set(N['need'])
def load(p):
    r=list(csv.reader(open(p,encoding='utf-8',errors='replace')))
    h=[i for i,x in enumerate(r) if x and x[0]=='index'][0]
    return {x[12].replace('\\','/').lower():x for x in r[h+1:] if len(x)>12}
def rank(n):
    l=n.lower()
    if l=='data1': return -1
    if l=='update': return 0
    if l=='update2': return 0.6
    if l=='update3': return 0.7
    return int(re.search(r'\d+',l).group())
order=[('desk',d) for d in sorted([d.name for d in (S/'dman').iterdir()],key=rank)]+[('global',g) for g in ['data2','data3','update','update2']]
src={}; allpaths=collections.defaultdict(set)
for kind,d in order:
    m=load(S/('dman' if kind=='desk' else 'man')/d/'manifest.csv')
    for n,x in m.items():
        if n.endswith('.spr'): allpaths[n.rsplit('/',1)[0]].add(n)
        if n in need: src[n]=[kind,d,x[12]]
json.dump(src,open('build/src_map.json','w'),indent=0)
json.dump({k:sorted(v) for k,v in allpaths.items()},open('build/all_spr_dirs.json','w'))
miss=sorted(need-set(src))
print('need',len(need),'found',len(src),'missing',len(miss))
print(collections.Counter(n.rsplit('_',1)[1] for n in miss))
print(collections.Counter(v[1] for v in src.values()))
print(miss[:20])
