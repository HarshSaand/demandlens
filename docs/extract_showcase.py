from pathlib import Path
import argparse, json, hashlib, sys
p=argparse.ArgumentParser();p.add_argument('--source', type=Path, required=True);a=p.parse_args()
S=a.source.resolve(); D=Path(__file__).resolve().parent; R=D.parent
D.mkdir(exist_ok=True)
import numpy as np
import pandas as pd
def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for c in iter(lambda:f.read(1048576),b''):h.update(c)
 return h.hexdigest()
def source(rel):return {'path':rel,'sha256':digest(S/rel)}
def write(data):
 import subprocess
 data['dataset_url']='https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page'
 data['source_code_commit']=subprocess.check_output(['git','-C',str(R),'rev-parse','HEAD'],text=True).strip()
 data['extractor_sha256']=digest(Path(__file__))
 data['sources']=sources
 data['source_repository']='https://github.com/HarshSaand/'+R.name
 data['extraction']='python docs/extract_showcase.py --source /path/to/reproduced/project'
 (D/'output-example.json').write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str)+'\n')
f='data/predictions.parquet';df=pd.read_parquet(S/f);x=df[(df.zone==43)&(df.fold=='may')].head(8);sources=[source(f),source('outputs/provenance.json')]
rows=[[str(r.hour)[11:16],f'{r.pred:.1f}',f'{r.lo:.1f} – {r.hi:.1f}',str(r['count'])] for _,r in x.iterrows()]
write(dict(title='DemandLens',subtitle='A day-ahead zone forecast you can inspect',eyebrow='ACTUAL HELD-OUT MODEL OUTPUT',context='NYC TLC zone 43 · 1 May 2024 · first 8 hours',columns=['Hour','Predicted pickups','90% interval','Observed pickups'],rows=rows,raw=x.to_dict('records'),note='LightGBM forecast from the saved May fold. Uses history available before the forecast day; observed counts are retrospective. No staffing savings or live deployment claim.',input='Historical zone-hour pickup counts and calendar',output='Hourly pickup forecast and calibrated interval'))
