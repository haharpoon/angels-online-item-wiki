"""Read-only extractor for Angels Online .pak members (raw DEFLATE at a known offset).
Usage: python pak_extract.py jobs.json out_dir
jobs.json: [[pak_path_without_ext, offset, compressed_size, decompressed_size, rel_out_path], ...]
Paks are opened read-only ('rb'); nothing is ever written to them."""
import json,sys,zlib,os,glob
jobs=json.load(open(sys.argv[1])); out=sys.argv[2]; fh={}; ok=bad=0
for pak,off,cs,ds,rel in jobs:
    if pak not in fh:
        cand=[p for p in glob.glob(pak+'.*') if p.lower().endswith('.pak')]
        fh[pak]=open(cand[0],'rb')
    f=fh[pak]; f.seek(off); data=zlib.decompress(f.read(cs),-15)
    if len(data)!=ds: bad+=1; continue
    p=os.path.join(out,rel); os.makedirs(os.path.dirname(p),exist_ok=True); open(p,'wb').write(data); ok+=1
print('ok',ok,'bad',bad)
