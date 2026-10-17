import re,json,csv,collections
from pathlib import Path
S=Path('/workspace/pets/src')
P={}
for m in re.finditer(r'<pet ([^>]*)/>',open(S/'pet.xml',encoding='utf-8').read()):
    a=dict(re.findall(r'(\S+?)="([^"]*)"',m.group(1))); P[a['編號']]=a
t=(S/'NPC.OBD').read_bytes().decode('cp950','replace')
O={}
for blk in t.split('[OBJECT]')[1:]:
    o={'sprites':{},'files':{}}
    for line in blk.splitlines():
        if '=' not in line: continue
        k,v=[x.strip() for x in line.split('=',1)]
        if k=='Sprite': n,rest=v.split(',',1); o['sprites'][n.strip()]=rest.strip()
        elif k=='SpriteFile': n,f=[x.strip() for x in v.split(',',1)]; o['files'][n]=f
        else: o[k]=v
    if 'Sequence' in o: O[o['Sequence']]=o
json.dump(P,open('build/pets_raw.json','w'),ensure_ascii=False)
json.dump(O,open('build/obd.json','w'),ensure_ascii=False)
seqs={a.get('圖號1') for a in P.values()}
miss=[s for s in seqs if s not in O]
print('forms',len(P),'seqs',len(seqs),'seq missing in OBD',len(miss),miss[:10])
print(collections.Counter(a.get('階段') for a in P.values()))
print(collections.Counter(O[s].get('Process') for s in seqs if s in O))
need=set()
for s in seqs:
    o=O.get(s)
    if not o: continue
    for act in ('Wait','Run','Att','Hurt','Dead'):
        f=o['files'].get(act)
        if f: need.add(('shape'+o['Directory'].replace('\\','/')+f).lower())
print('need spr',len(need))
avail={}
for pak in ['data2','data3','update','update2']:
    r=list(csv.reader(open(S/f'man/{pak}/manifest.csv',encoding='utf-8',errors='replace')))
    h=[i for i,x in enumerate(r) if x and x[0]=='index'][0]
    for x in r[h+1:]:
        if len(x)>12: avail[x[12].lower()]=(pak,x[12])
have=[n for n in need if n in avail]
print('in global paks',len(have))
json.dump({'need':sorted(need),'avail':{n:avail[n] for n in have}},open('build/need.json','w'),indent=0)
