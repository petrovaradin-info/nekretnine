"""Flat import feed with Serbian column names and explicit price units."""
import re
import logging
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,quote
from .export import write_json
COLUMNS=['naslov','kategorija','opis','cena','link','id','slika_url','kontakt_ime','kontakt_email','kontakt_tel','lokacija','tip_nekretnine','tip_ponude','povrsina','broj_soba','datum_objave','valuta','osnova_cene']

MAX_TITLE_LENGTH=200

def export_title(value):
    value=' '.join(str(value or '').split())
    if len(value)<=MAX_TITLE_LENGTH:return value
    prefix=value[:MAX_TITLE_LENGTH-3]
    if ' ' in prefix:prefix=prefix.rsplit(' ',1)[0]
    return prefix.rstrip()+'...'

def export_url(value):
    if not value:return ''
    try:
        parts=urlsplit(str(value).strip())
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:return ''
        host=parts.hostname.encode('idna').decode('ascii')
        if re.search(r'[^a-zA-Z0-9.:-]',host):return ''
        if ':' in host:host='['+host+']'
        if parts.port:host+=':'+str(parts.port)
        def component(text,safe):
            text=re.sub(r'%(?![0-9a-fA-F]{2})','%25',text)
            return quote(text,safe=safe+'%')
        return urlunsplit((parts.scheme,host,component(parts.path,'/'),component(parts.query,'=&/?+'),component(parts.fragment,'')))
    except (ValueError,UnicodeError):return ''

def record(ad):
    return dict(naslov=export_title(ad.get('title','')),kategorija='Nekretnine',opis=ad.get('description',''),cena=ad.get('price'),link=ad['url'],id=f"{ad['source']}:{ad.get('source_id','')}",slika_url=export_url(next((p.get('url','') for p in ad.get('photos',[]) if p.get('url')),'')),kontakt_ime=ad.get('advertiser',''),kontakt_email=ad.get('contact_email',''),kontakt_tel=ad.get('contact_tel',''),lokacija=ad.get('location',''),tip_nekretnine=ad.get('property_type',''),tip_ponude=ad.get('transaction',''),povrsina=ad.get('plot_area_m2') if ad.get('property_type')=='plac' else ad.get('area_m2'),broj_soba=ad.get('rooms',''),datum_objave=ad.get('published_at',''),valuta=ad.get('currency',''),osnova_cene=ad.get('price_basis','unknown'))

MAX_LISTINGS=4999

def export_feed(path,rows,fmt='json'):
    if fmt!='json':raise ValueError('Import izvoz podrzava samo JSON')
    path=Path(path)
    if path.suffix.lower()!='.json':raise ValueError('Putanja za izvoz mora imati .json ekstenziju')
    values=[record(ad) for ad in sorted(rows,key=lambda ad:ad['url'])]
    chunks=[values[i:i+MAX_LISTINGS] for i in range(0,len(values),MAX_LISTINGS)] or [[]]
    paths=[]
    for index,chunk in enumerate(chunks,1):
        output=path.with_name(f'{path.stem}-{index:03d}.json')
        write_json(output,chunk);paths.append(output)
    # Remove only this feed's obsolete outputs after all new parts have been written.
    pattern=re.compile(re.escape(path.stem)+r'-[0-9]{3,}\.json$')
    for candidate in path.parent.iterdir():
        if candidate.is_file() and pattern.fullmatch(candidate.name) and candidate not in paths:candidate.unlink()
    if path.is_file():path.unlink()
    legacy_csv=path.with_suffix('.csv')
    if legacy_csv.is_file():
        try:legacy_csv.unlink()
        except PermissionError:logging.getLogger(__name__).warning('Stari CSV je otvoren u drugom programu; novi izvoz je samo JSON: %s',legacy_csv)
    return paths
