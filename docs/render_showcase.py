"""Render the committed actual-output JSON as a self-contained review page."""
from pathlib import Path
import json,html
D=Path(__file__).resolve().parent
j=json.loads((D/'output-example.json').read_text())
e=lambda x:html.escape(str(x))
parts=[]
if 'images' in j:
 parts.append('<div class="images">'+''.join(f'<figure><img src="{e(x["path"])}" alt="{e(x["label"])}"><figcaption>{e(x["label"])}</figcaption></figure>' for x in j['images'])+'</div>')
if 'rows' in j:
 parts.append('<table><thead><tr>'+''.join('<th>'+e(c)+'</th>' for c in j['columns'])+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(c)+'</td>' for c in r)+'</tr>' for r in j['rows'])+'</tbody></table>')
if 'blocks' in j:
 for label,text in j['blocks']:
  parts.append(f'<section><h3>{e(label)}</h3><div class="prose">{e(text)}</div></section>')
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>
*{box-sizing:border-box}body{margin:0;background:#eef0eb;color:#162526;font-family:Arial,Helvetica,sans-serif;padding:46px 58px;width:1440px;min-height:900px}header{display:flex;flex-wrap:wrap;gap:14px;min-width:0;align-items:center;justify-content:space-between;border-bottom:1px solid #b9c7bf;padding-bottom:17px}.brand{min-width:0;overflow-wrap:anywhere;font-weight:700;font-size:25px}.tag{min-width:0;max-width:100%;overflow-wrap:anywhere;text-align:right;font-size:13px;letter-spacing:1.6px;color:#4e6861}h1{font-size:40px;line-height:1.18;letter-spacing:-1.2px;margin:32px 0 13px;font-weight:600}.context{font-size:17px;color:#536660;margin:0 0 26px}.panel{background:#fff;border:1px solid #d1dcd6;border-radius:16px;padding:25px}table{border-collapse:collapse;width:100%;font-size:19px}th{text-align:left;font-size:13px;letter-spacing:.8px;text-transform:uppercase;color:#536660;background:#eff5f0}th,td{padding:14px 16px;border-bottom:1px solid #e2e9e5}td{font-variant-numeric:tabular-nums}tr:last-child td{border:0}td:last-child{font-weight:600;color:#17624b}.note{max-width:100%;overflow-wrap:anywhere;white-space:normal;font-size:16px;line-height:1.5;color:#536660;margin:24px 2px 0}footer{display:flex;flex-wrap:wrap;gap:20px;border-top:1px solid #c8d5ce;margin-top:27px;padding-top:18px;color:#435a53;font-size:14px}footer a{color:#17624b}section+section{border-top:1px solid #dce6e0;margin-top:20px;padding-top:10px}h3{font-size:12px;letter-spacing:1.4px;color:#536660;margin:0 0 12px}.prose{font-size:21px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}.images{display:flex;gap:18px;align-items:center}.images figure{margin:0;flex:1;min-width:0}.images img{width:100%;display:block;border-radius:8px;max-height:480px;object-fit:contain;background:#0c1216}.images figcaption{font-size:15px;margin-top:12px;color:#536660}.io{display:flex;gap:35px;font-size:15px;padding:18px 0 0}.io b{display:block;font-size:11px;letter-spacing:1px;color:#73847d;margin-bottom:5px}
</style>'''
page+=f'<title>{e(j["title"])} actual output</title><header><span class="brand">{e(j["title"])}</span><span class="tag">{e(j["eyebrow"])}</span></header><h1>{e(j["subtitle"])}</h1><p class="context">{e(j["context"])}</p><div class="panel">'+''.join(parts)+'</div>'
page+=f'<div class="io"><div><b>INPUT</b>{e(j["input"])}</div><div><b>OUTPUT</b>{e(j["output"])}</div></div><p class="note">{e(j["note"])}</p><footer><span>Rendered from actual saved results or reproduced inference</span><a href="output-example.json">Inspect source record + SHA-256 provenance ↗</a></footer></html>'
(D/'output-showcase.html').write_text(page)
