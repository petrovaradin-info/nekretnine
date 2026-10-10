"""Explainable, conservative grouping; every original listing is retained."""
from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
import re
from .model import norm, LOCATIONS
from .photos import photo_matches


def room_count(raw):
    value=norm(raw)
    words={'garsonjera':'0.5','jednosoban':'1','jednoiposoban':'1.5','dvosoban':'2','dvoiposoban':'2.5','trosoban':'3','troiposoban':'3.5','cetvorosoban':'4','cetvoroiposoban':'4.5','petosoban':'5','sestosoban':'6'}
    if value in words: return words[value]
    m=re.search(r'^([0-9]+(?:[.,][0-9]+)?)\b',value)
    return str(float(m[1].replace(',','.'))).removesuffix('.0') if m else value


def floor_number(raw):
    value=norm(raw)
    if 'visoko prizemlje' in value: return 'vp'
    if value in ('prizemlje','prizemni'): return '0'
    m=re.match(r'^(\d+)',value)
    return m[1] if m else value


def compare(a,b):
    if a['url']==b['url']: return None
    if (a.get('transaction'),a.get('property_type'),a.get('location')) != (b.get('transaction'),b.get('property_type'),b.get('location')): return None
    if a.get('location') not in LOCATIONS: return None
    if a.get('currency') != b.get('currency') or a.get('price_basis') != b.get('price_basis'): return None
    size_key='plot_area_m2' if a['property_type']=='plac' else 'area_m2'
    sa,sb=a.get(size_key),b.get(size_key)
    if not sa or not sb or abs(sa-sb)>max(1,min(sa,sb)*0.02): return None
    for key,normalize in [('rooms',room_count),('floor',floor_number),('address',norm)]:
        va,vb=normalize(a.get(key,'')),normalize(b.get(key,''))
        if va and vb and va!=vb: return None
    pa,pb=a.get('plot_area_m2'),b.get('plot_area_m2')
    if a['property_type']=='kuca' and pa and pb and abs(pa-pb)>max(1,min(pa,pb)*0.02): return None
    advertiser=bool(a.get('advertiser') and b.get('advertiser') and norm(a['advertiser'])==norm(b['advertiser']))
    ca,cb=a.get('agency_id'),b.get('agency_id')
    if advertiser and ca and cb and ca!=cb: return None
    agency=bool(advertiser and ca and ca==cb)
    da,db=norm(a.get('description','')),norm(b.get('description',''))
    similarity=SequenceMatcher(None,da,db,autojunk=False).ratio() if da and db else 0
    full=not a.get('description_incomplete') and not b.get('description_incomplete') and min(len(da),len(db))>=200
    photos=photo_matches(a.get('photos',[]),b.get('photos',[]))
    price_a,price_b=a.get('price'),b.get('price')
    price_gap=abs(price_a-price_b)/max(price_a,price_b) if price_a and price_b else None
    close_price=price_gap is not None and price_gap<=0.1
    known_layout=all(a.get(k) and b.get(k) for k in ('rooms','floor'))
    conflicts=any('title_area_conflict' in r.get('review_reasons',[]) or 'search_category_conflict' in r.get('review_reasons',[]) or 'title_location_conflict' in r.get('review_reasons',[]) for r in (a,b))
    reasons=[]
    if agency: reasons.append('same_agency_and_property_code')
    if photos: reasons.append(f'{photos}_matching_photos')
    if full and similarity>=0.9: reasons.append('similar_full_description')
    # Price and area alone are never a sufficient identity signal.
    if not reasons: return None
    automatic=not conflicts and (
        (agency and (price_gap is None or price_gap<=0.25)) or
        (photos>=2 and close_price and ((full and similarity>=0.8) or known_layout)) or
        (full and similarity>=0.97 and close_price and known_layout))
    if not automatic and not (agency or photos or (full and similarity>=0.9 and close_price)): return None
    return {'urls':sorted([a['url'],b['url']]),'automatic':automatic,'review_required':not automatic,
            'reasons':reasons,'matching_photos':photos,'description_similarity':round(similarity,3),
            'price_difference_ratio':round(price_gap,4) if price_gap is not None else None,
            'area_difference_m2':round(abs(sa-sb),3)}


def comparisons(rows):
    buckets=defaultdict(list)
    for row in rows:
        if row.get('location') in LOCATIONS:
            buckets[(row['transaction'],row['property_type'],row['location'],row.get('currency'),row.get('price_basis'))].append(row)
    edges=[]
    for bucket in buckets.values():
        key='plot_area_m2' if bucket[0]['property_type']=='plac' else 'area_m2'
        bucket=sorted((r for r in bucket if r.get(key)),key=lambda r:(r[key],r['url']))
        for i,a in enumerate(bucket):
            for b in bucket[i+1:]:
                if b[key]-a[key]>max(1,a[key]*0.02): break
                evidence=compare(a,b)
                if evidence: edges.append(evidence)
    return sorted(edges,key=lambda e:e['urls'])


def groups(rows):
    rows=sorted(rows,key=lambda r:r['url'])
    rows=[r for r in rows if r.get('location') in LOCATIONS]
    edges=comparisons(rows)
    automatic={tuple(e['urls']):e for e in edges if e['automatic']}
    clusters=[]
    for row in rows:
        # Complete-link grouping prevents A~B~C chaining where A contradicts C.
        cluster=next((c for c in clusters if all(tuple(sorted((row['url'],m['url']))) in automatic for m in c)),None)
        if cluster is None: clusters.append([row])
        else: cluster.append(row)
    output=[]
    for members in clusters:
        representative=max(members,key=lambda r:(len(r.get('photos',[])),len(r.get('description','')),r['url']))
        result=dict(representative)
        urls=[m['url'] for m in members]
        result['group_id']='property-'+hashlib.sha256('\n'.join(urls).encode()).hexdigest()[:16]
        result['listing_count']=len(members)
        result['status']='observed' if any(m.get('status','observed')=='observed' for m in members) else 'unavailable'
        result['listings']=members
        result['sources']=[{'source':m['source'],'url':m['url'],'price':m.get('price'),'currency':m.get('currency'),'price_basis':m.get('price_basis'),'status':m.get('status','observed')} for m in members]
        result['matching_evidence']=[e for e in edges if e['automatic'] and all(u in urls for u in e['urls'])]
        result['review_reasons']=sorted({reason for m in members for reason in m.get('review_reasons',[])})
        prices=[m['price'] for m in members if m.get('price') is not None]
        result['price_min']=min(prices) if prices else None
        result['price_max']=max(prices) if prices else None
        output.append(result)
    return output
