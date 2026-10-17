"""Build docs/pets/ data for pets.html.
Inputs (src/): pet.xml (UPDATE24 eng), NPC.OBD (update26), petattrib.xml (update26), spr/ (extracted read-only from paks).
Outputs: <out>/pets-data.js and <out>/sheets/<set>.png  (8-bit grayscale: pixel value = palette index, 0 = transparent).
Palettes (RGB565 -> hex) live in pets-data.js so the colour-shift formula can work on true palette indices."""
import sys,json,re,struct,hashlib,collections
from pathlib import Path

from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1])); import ewsp
from shp_icon import rgb565
OUT=Path(sys.argv[1]); (OUT/'sheets').mkdir(parents=True,exist_ok=True)
P=json.load(open('build/pets_raw.json')); O=json.load(open('build/obd.json'))
SPR=Path('src/spr')
ACTS=['Wait','Run','Att','Hurt','Dead']
STAGE={'原型':0,'初階':1,'中階':2,'高階':3,'頂階':4}
TYPE_EN={'攻擊型':'Attack','防禦型':'Defence','攻防並重型':'Balanced Atk/Def','血牛型':'Tank (HP)','平均型':'Average','敏捷型':'Agile','魔攻型':'Magic Attack','輔助回復型':'Support/Heal','遠程攻擊型':'Ranged','火屬性攻擊型':'Fire Attack','水屬性平均型':'Water Average','雷屬性敏捷型':'Lightning Agile','硬漢型':'Tough','魔力型':'Mana','大地強壯型':'Earth Sturdy','風雷迅速型':'Wind/Thunder Swift','火焰攻擊型':'Flame Attack','寒冰防禦型':'Ice Defence','萬能型':'All-round','強攻型':'Assault','輔助攻擊型':'Support Attack','迅捷型':'Swift','堅守型':'Guardian'}
FAM_EN={'人型':'Humanoid','能量':'Energy','動物':'Animal','植物':'Plant','昆蟲':'Insect','不死':'Undead','元素':'Elemental','人形':'Humanoid','龍族':'Dragon','惡魔':'Demon','機械':'Machine','天使':'Angel','精靈':'Spirit'}
# stats: level 1 and highest level per pet type
ST=collections.defaultdict(dict)
for m in re.finditer(r'<petattrib ([^>]*)/>',open('src/petattrib.xml',encoding='utf-8').read()):
    a=dict(re.findall(r'(\S+?)="([^"]*)"',m.group(1))); ST[a['寵物類型']][int(a['等級'])]=a
SK=[('HP','HP'),('MP','MP'),('平均攻擊','Atk'),('防禦','Def'),('魔攻','M.Atk'),('魔防','M.Def'),('精準','Acc'),('靈敏','Agi')]
def stats(t):
    s=ST.get(t)
    if not s: return None
    lv=sorted(s); lo,hi=s[lv[0]],s[lv[-1]]
    return {'lvMax':lv[-1],'rows':[[lab,int(lo[k]),int(hi[k])] for k,lab in SK if k in lo]}
def anim(spec):
    seq=[];delay=8
    for tok in [x.strip() for x in spec.split(',')]:
        if tok.startswith('#'): delay=int(tok[1:])
        m=re.match(r'^[a-z](\d\d)\d\*$',tok)
        if m: seq.append(int(m.group(1))-1)
    return seq,delay
sheets={}
def decode_file(p):
    """Decode one EWSP .spr into an index sheet (5 dirs x phases). Returns (png_name, meta) or None."""
    data=p.read_bytes()
    if data[:4]!=b'EWSP': return None
    palo=struct.unpack_from('<I',data,16)[0]
    pal='|'.join('%02x%02x%02x'%rgb565(struct.unpack_from('<H',data,palo+i*2)[0]) for i in range(256))
    fr=[]
    for s in ewsp.tlhs_starts(data):
        if s+80>len(data): fr.append(None); continue
        w,h=struct.unpack_from('<II',data,s+20); hx,hy=struct.unpack_from('<ii',data,s+28)
        px=struct.unpack_from('<I',data,s+44)[0]
        if not(0<w<=512 and 0<h<=512): fr.append(None); continue
        offs=[struct.unpack_from('<I',data,s+80+r*4)[0] for r in range(h)]
        im=bytearray(w*h)
        for r in range(h):
            q=s+offs[r]; end=s+(offs[r+1] if r+1<h else px)
            while q+8<=end and q+8<=len(data):
                c,dx=struct.unpack_from('<hh',data,q); src=s+struct.unpack_from('<I',data,q+4)[0]; q+=8
                if c<0: break
                c=max(0,min(c,w-dx,len(data)-src))
                if dx>=0 and c>0: im[r*w+dx:r*w+dx+c]=data[src:src+c]
        fr.append((Image.frombytes('L',(w,h),bytes(im)),hx,hy))
    ok=[f for f in fr if f]
    if not ok: return None
    phases=(len(fr)+4)//5
    cw=max(f[0].width for f in ok); ch=max(f[0].height for f in ok)
    sheet=Image.new('L',(5*cw,phases*ch),0); meta=[]
    for i,f in enumerate(fr):
        if not f: meta.append(None); continue
        ph,di=divmod(i,5); sheet.paste(f[0],(di*cw,ph*ch)); meta.append([di*cw,ph*ch,f[0].width,f[0].height,f[1],f[2]])
    name=hashlib.sha1(sheet.tobytes()).hexdigest()[:12]
    out=OUT/'sheets'/(name+'.png')
    if not out.exists(): sheet.save(out,optimize=True)
    return {'img':name,'pal':pal,'f':meta,'phases':phases}
def _job(p): return str(p),decode_file(p)
def set_for(o):
    d=o['Directory'].strip('\\').replace('\\','/').lower(); acts={}
    for a in ACTS:
        f=o['files'].get(a)
        if not f: continue
        p=SPR/'shape'/d/f.lower(); sh=sheets.get(str(p))
        if not sh: continue
        seq,delay=anim(o['sprites'].get(a,''))
        acts[a]={'sheet':sh,'seq':[min(x,sh['phases']-1) for x in seq] or list(range(sh['phases'])),'delay':delay,'file':f}
    return acts
import multiprocessing as mp
files=sorted({SPR/'shape'/o['Directory'].strip('\\').replace('\\','/').lower()/o['files'][a].lower() for o in [O[P[x]['圖號1']] for x in P if P[x].get('圖號1') in O] for a in ACTS if o['files'].get(a)})
files=[f for f in files if f.exists()]
with mp.Pool(8) as pool:
    for k,v in pool.imap_unordered(_job,files,8):
        if v: sheets[k]=v
print('decoded',len(files),'ok',len(sheets))
forms={}; cjk=re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]')
for pid,a in P.items():
    seq=a.get('圖號1'); o=O.get(seq,{})
    acts=set_for(o) if o else {}
    st=stats(a.get('寵物類型'))
    nx=[x for x in (a.get('升階變化1'),a.get('升階變化2')) if x and x!='0' and x in P]
    forms[pid]={'id':int(pid),'name':a['名稱'],'nonEn':bool(cjk.search(a['名稱'])),'stage':STAGE.get(a.get('階段'),-1),
      'type':a.get('寵物類型'),'typeEn':TYPE_EN.get(a.get('寵物類型')),'family':a.get('系別'),'familyEn':FAM_EN.get(a.get('系別')),
      'exp':a.get('經驗等級表'),'move':a.get('移動速度'),'atkSpd':a.get('攻擊速度'),'range':a.get('攻擊範圍'),'crit':a.get('重擊機率'),
      'next':nx,'seq':int(seq) if seq else None,'obdName':o.get('Name'),'acts':acts,'dir':o.get('Directory'),
      'baseBias':o.get('BaseBias'),'maskBias':o.get('MaskBias'),'biasFlag':'SP_ATTRIB_BIAS' in o.get('Flags',''),
      'zoom':float(o.get('ZoomX',1)), 'stats':st}
# Top-stage forms have no 升階變化 parent: they are Fusion Pets. Link each to its 'Fusion Pet <name>' item from the item wiki catalog.
try:
    _t=open(sys.argv[2] if len(sys.argv)>2 else 'docs/items.html',encoding='utf-8').read(); _i=_t.index('const DATA = ')+13
    _D,_=json.JSONDecoder().raw_decode(_t[_i:])
    FUS={d.get('raw') if d.get('prefix')=='Fusion Pet' else d['name']:d for d in _D if d.get('kind')=='Pet' and 'usion' in d['name']}
except Exception as e:
    print('no item catalog for fusion links',e); FUS={}
for f in forms.values():
    if f['stage']==4:
        d=FUS.get(f['name']); f['fusionItem']={'id':d['id'],'name':d['name'],'desc':d.get('desc','')} if d else None
# parents + routes
par=collections.defaultdict(list)
for pid,f in forms.items():
    for n in f['next']: par[n].append(pid)
for pid,f in forms.items(): f['prev']=par.get(pid,[])
def route(pid):
    path=[pid]; seen={pid}
    while forms[path[0]]['prev']:
        p=[x for x in forms[path[0]]['prev'] if x not in seen]
        if not p: break
        path.insert(0,p[0]); seen.add(p[0])
    return path
for pid,f in forms.items():
    if f['stage']==4: f['route']=route(pid)
# dedupe palettes + action sheets into tables
pt={}; st={}
for f in forms.values():
    for a in f['acts'].values():
        sh=a.pop('sheet'); k=sh['img']
        if k not in st: st[k]={'img':k,'f':sh['f']}
        a['img']=k; a['pal']=pt.setdefault(sh['pal'],len(pt))
pals=[k.split('|') for k,_ in sorted(pt.items(),key=lambda x:x[1])]
js='window.PET_DATA='+json.dumps({'forms':forms,'sheets':st,'palettes':pals},ensure_ascii=False,separators=(',',':'))+';\n'
(OUT/'pets-data.js').write_text(js,encoding='utf-8')
# coverage
cov=collections.Counter()
for f in forms.values():
    n=len(f['acts']); cov['forms']+=1; cov['acts_%d'%n]+=1
    cov['withWait']+= 'Wait' in f['acts']; cov['withAnySprite']+= n>0
    if f['stage']==4: cov['top']+=1; cov['topWithSprite']+= n>0
print(dict(cov),'sheets',len(st),'palettes',len(pals),'js bytes',len(js))
json.dump(dict(cov),open('build/coverage.json','w'))
