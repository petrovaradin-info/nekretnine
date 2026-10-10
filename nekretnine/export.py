import csv
import html
import json
from difflib import SequenceMatcher
from .model import norm


def candidates(rows):
    output = []
    for i, a in enumerate(rows):
        for b in rows[i+1:]:
            if a['source'] == b['source']: continue
            if (a['transaction'],a['property_type'],a['location']) != (b['transaction'],b['property_type'],b['location']): continue
            if not a['location']: continue
            size_key = 'plot_area_m2' if a['property_type'] == 'plac' else 'area_m2'
            size_a,size_b = a[size_key],b[size_key]
            if not size_a or not size_b or abs(size_a-size_b) > max(1,size_a*0.02): continue
            if a['price_basis'] != b['price_basis'] or a['currency'] != b['currency']: continue
            if a['price'] is None or b['price'] is None or abs(a['price']-b['price']) > max(1,a['price']*0.03): continue
            desc_a,desc_b = norm(a['description']),norm(b['description'])
            score = SequenceMatcher(None, desc_a, desc_b, autojunk=False).ratio()
            same_agency = bool(a['agency_id'] and a['agency_id']==b['agency_id'] and a['advertiser'] and norm(a['advertiser'])==norm(b['advertiser']))
            if same_agency or (min(len(desc_a),len(desc_b)) >= 160 and score >= 0.9):
                output.append({'urls':[a['url'],b['url']], 'similarity':round(score,3), 'reason':'agency_id' if same_agency else 'description_area_price', 'review_required':True})
    return output

def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def export(path, rows, fmt):
    if fmt == 'json': write_json(path, rows); return
    columns = ['title','transaction','property_type','location','location_raw','price','currency','price_basis','area_m2','plot_area_m2','rooms','floor','heating','advertiser','url','source','updated_at','first_seen','last_seen','status','review_reasons']
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,delimiter=';'); writer.writeheader()
        for row in rows:
            values={k:row.get(k,'') for k in columns}
            for k,v in values.items():
                if isinstance(v,list): v=' | '.join(v)
                if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')): v="'"+v
                values[k]=v
            writer.writerow(values)

def report(path, rows):
    cards=[]
    e=lambda x:html.escape(str(x if x is not None else ''),quote=True)
    for a in rows:
        label='Stan' if a['property_type']=='stan' else 'Kuća' if a['property_type']=='kuca' else 'Plac' if a['property_type']=='plac' else 'Poslovni prostor'
        size=f"Objekat: {a['area_m2']} m²" if a['area_m2'] else ''
        if a['plot_area_m2']: size+=f" · Plac: {a['plot_area_m2']} m²"
        review=', '.join(a['review_reasons'])
        cards.append(f'<article data-transaction="{e(a["transaction"])}" data-kind="{e(a["property_type"])}" data-review="{bool(review)}"><small>{e(a["transaction"])} · {label} · {e(a["source"])}</small><h2><a href="{e(a["url"])}" target="_blank" rel="noopener noreferrer">{e(a["title"])}</a></h2><p>{e(a["price"])} {e(a["currency"])} · {e(a["price_basis"])}</p><p>{e(size)} · {e(a["location_raw"])}</p><p>{e(a["rooms"])} · {e(a["floor"])}</p><p>{e(a["advertiser"])}</p><small>Poslednji put viđen: {e(a["last_seen"])} · {e(a["status"])}</small><p class="review">{e(review)}</p><details><summary>Opis</summary><p>{e(a["description"])}</p></details></article>')
    page="""<!doctype html><html lang="sr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nekretnine — Petrovaradin</title><style>body{font:16px system-ui;background:#f4f6f8;color:#172c39;max-width:1100px;margin:auto;padding:24px}header{position:sticky;top:0;background:#f4f6f8;padding:12px 0}input,select{font:inherit;padding:9px;margin:4px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}article{background:white;padding:20px;border-radius:12px;box-shadow:0 2px 8px #0001}article[hidden]{display:none}h2{font-size:19px}a{color:#176c72}.review{color:#955d13;font-size:13px}small{color:#667}</style><header><h1>Nekretnine — Petrovaradin</h1><p>Lokalni snimak prikupljenih oglasa. Status observed znači da je oglas viđen, bez potvrde dostupnosti.</p><input id="q" placeholder="Pretraga"><select id="transaction"><option value="">Prodaja i izdavanje</option>prodaja</option>izdavanje</option></select><select id="kind"><option value="">Sve vrste</option value="stan">Stan</option><option value="kuca">Kuća</option><option value="poslovni_prostor">Poslovni prostor</option><option value="plac">Plac</option></select><label><input type="checkbox" id="review">Potrebna provera</label><p id="count"></p></header><main>CARDS</main><script>const cards=[...document.querySelectorAll('article')];function filter(){let n=0;cards.forEach(c=>{c.hidden=!(c.textContent.toLowerCase().includes(q.value.toLowerCase())&&(!transaction.value||c.dataset.transaction===transaction.value)&&(!kind.value||c.dataset.kind===kind.value)&&(!review.checked||c.dataset.review==='True'));if(!c.hidden)n++});document.getElementById('count').textContent=n+' oglasa'}document.querySelectorAll('input,select').forEach(x=>x.addEventListener('input',filter));filter()</script></html>"""
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(page.replace('CARDS',''.join(cards)),encoding='utf-8')
