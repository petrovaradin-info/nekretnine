import csv
import html
import json


def candidates(rows):
    from .grouping import comparisons
    return comparisons(rows)


def write_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def export(path, rows, fmt, flat=False):
    from .grouping import groups
    grouped = groups(rows)
    if fmt == 'json': write_json(path, rows if flat else grouped); return
    membership = {ad['url']:(g['group_id'],g['listing_count']) for g in grouped for ad in g['listings']}
    rows = [dict(ad, group_id=membership.get(ad['url'],('',1))[0], group_size=membership.get(ad['url'],('',1))[1]) for ad in rows]
    columns = ['group_id','group_size','title','transaction','property_type','location','location_raw','price','currency','price_basis','area_m2','plot_area_m2','rooms','floor','heating','advertiser','url','source','updated_at','first_seen','last_seen','status','review_reasons']
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
    from .grouping import groups
    grouped = groups(rows)
    cards=[]
    e=lambda x:html.escape(str(x if x is not None else ''),quote=True)
    basis={'monthly':'mesečno','total':'ukupna cena','daily':'dnevno','per_person':'po osobi','unknown':'jedinica cene nepoznata'}
    labels={'stan':'Stan','kuca':'Kuća','plac':'Plac','poslovni_prostor':'Poslovni prostor'}
    def price(ad):
        value=ad.get('price')
        shown=f'{value:,.2f}' if value is not None else 'Cena nije navedena'
        return e(shown+' '+ad.get('currency','')+' · '+basis.get(ad.get('price_basis'),'nepoznato'))
    for group in grouped:
        member_cards=[]
        for ad in group['listings']:
            photos=ad.get('photos',[])
            photo=next((p['url'] for p in photos if p.get('url','').startswith(('https://','http://'))),'')
            image=f'<img loading="lazy" src="{e(photo)}" alt="Fotografija nekretnine">' if photo else ''
            member_cards.append(f'<section class="source">{image}<h3><a href="{e(ad["url"])}" target="_blank" rel="noopener noreferrer">{e(ad["source"])} — {e(ad["title"])}</a></h3><p>{price(ad)}</p><p>{e(ad.get("advertiser",""))} · {e(ad.get("rooms",""))} · {e(ad.get("floor",""))}</p><small>Ažuriran: {e(ad.get("updated_at",""))} · Viđen: {e(ad.get("last_seen",""))} · {e(ad.get("status","observed"))}</small><details><summary>Opis izvornog oglasa</summary><p>{e(ad.get("description",""))}</p></details></section>')
        size=f'Objekat: {group["area_m2"]} m²' if group.get('area_m2') else ''
        if group.get('plot_area_m2'): size+=f' · Plac: {group["plot_area_m2"]} m²'
        review=', '.join(group.get('review_reasons',[]))
        evidence='; '.join(', '.join(item['reasons']) for item in group['matching_evidence'])
        prices=price(group) if group['price_min']==group['price_max'] else e(str(group['price_min'])+' – '+str(group['price_max'])+' '+group.get('currency','')+' · '+basis.get(group.get('price_basis'),'nepoznato'))
        cards.append(f'<article data-transaction="{e(group["transaction"])}" data-kind="{e(group["property_type"])}" data-location="{e(group["location"])}" data-review="{bool(review)}"><small>{e(group["transaction"])} · {labels[group["property_type"]]} · {e(group["location"])}</small><h2>{e(group["title"])}</h2><p>{prices}</p><p>{e(size)}</p><p class="badge">{group["listing_count"]} izvornih oglasa u grupi</p><p class="review">{e(review)}</p><details open><summary>Svi izvorni oglasi</summary>{"".join(member_cards)}</details><details><summary>Razlozi grupisanja</summary><p>{e(evidence) or "Samostalan oglas; nema dovoljno dokaza za spajanje."}</p></details></article>')
    page="""<!doctype html><html lang="sr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nekretnine — Petrovaradin i okolina</title><style>body{font:16px system-ui;background:#f4f6f8;color:#172c39;max-width:1200px;margin:auto;padding:24px}header{background:#f4f6f8;padding:12px 0}input,select{font:inherit;padding:9px;margin:4px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}article{background:white;padding:20px;border-radius:12px;box-shadow:0 2px 8px #0001}article[hidden]{display:none}h2{font-size:19px}h3{font-size:16px}a{color:#176c72}.review{color:#955d13;font-size:13px}small{color:#667}.source{border-top:1px solid #dde;padding:14px 0;overflow:auto}.source img{width:130px;height:95px;object-fit:cover;float:right;margin:0 0 8px 10px;border-radius:6px}.badge{font-size:13px;background:#e5f4f1;padding:8px}details{margin:8px 0}summary{cursor:pointer}</style><header><h1>Nekretnine — Petrovaradin i okolina</h1><p>Petrovaradin, Sremska Kamenica i Sremski Karlovci. Iste nekretnine su grupisane; svi izvorni oglasi, cene i linkovi ostaju dostupni.</p><input id="q" placeholder="Pretraga"><select id="transaction"><option value="">Prodaja i izdavanje</option>prodaja</option>izdavanje</option></select><select id="kind"><option value="">Sve vrste</option value="stan">Stan</option><option value="kuca">Kuća</option><option value="poslovni_prostor">Poslovni prostor</option><option value="plac">Plac</option></select><select id="place"><option value="">Sva tri mesta</option>Petrovaradin</option><option>Sremska Kamenica</option><option>Sremski Karlovci</option></select><label><input type="checkbox" id="review">Potrebna provera</label><p id="count"></p></header><main>CARDS</main><script>const cards=[...document.querySelectorAll('article')];const q=document.getElementById('q'),transaction=document.getElementById('transaction'),kind=document.getElementById('kind'),place=document.getElementById('place'),review=document.getElementById('review');function filter(){let n=0;cards.forEach(c=>{c.hidden=!(c.textContent.toLowerCase().includes(q.value.toLowerCase())&&(!transaction.value||c.dataset.transaction===transaction.value)&&(!kind.value||c.dataset.kind===kind.value)&&(!place.value||c.dataset.location===place.value)&&(!review.checked||c.dataset.review==='True'));if(!c.hidden)n++});document.getElementById('count').textContent=n+' grupa nekretnina'}document.querySelectorAll('input,select').forEach(x=>x.addEventListener('input',filter));filter()</script></html>"""
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(page.replace('CARDS',''.join(cards)),encoding='utf-8')
