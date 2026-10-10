import json
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from bs4 import BeautifulSoup
from .model import Listing, canonical, number, area, norm


def text(node): return node.get_text(" ", strip=True) if node else ""

def schema(soup):
    def walk(value):
        if isinstance(value, dict):
            yield value
            for v in value.values(): yield from walk(v)
        elif isinstance(value, list):
            for v in value: yield from walk(v)
    for node in soup.select('script[type="application/ld+json"]'):
        try: yield from walk(json.loads(node.get_text()))
        except (ValueError, TypeError): continue

def has_type(row, name):
    t = row.get("@type", [])
    return name in (t if isinstance(t, list) else [t])

def breadcrumb(rows):
    output = []
    for row in rows:
        if has_type(row, "BreadcrumbList"):
            for part in row.get("itemListElement", []):
                item = part.get("item", {})
                output.append(part.get("name") or (item.get("name", "") if isinstance(item, dict) else ""))
    return output

def listing_page(html, url, source):
    soup = BeautifulSoup(html, "html.parser")
    found, pages = {}, []
    p = urlsplit(url)
    page_key = "p" if source == "oglasi" else "strana"
    for a in soup.select("a[href]"):
        target = urljoin(url, a["href"])
        q = urlsplit(target)
        if q.scheme not in ("http", "https") or q.netloc != p.netloc: continue
        detail = (re.search(r"^/oglas/03-[0-9]+/", q.path) if source == "oglasi"
                  else re.search(r"^/(?:prodaja|izdavanje)-[^/]+/[^/]+/.*[a-f0-9]{24}$", q.path))
        if detail and (source != "4zida" or q.path.startswith(p.path.rstrip("/") + "/")):
            found[canonical(target)] = text(a)
        elif q.path == p.path and page_key in parse_qs(q.query) and target != url:
            pages.append(target)
    empty = bool(re.search(r"(?:\b0 oglasa\b|nema (?:oglasa|rezultata)|nije pronađen)", text(soup.select_one("main") or soup), re.I))
    return list(found), list(dict.fromkeys(pages)), empty

def classify(category):
    value = norm(category)
    transaction = "prodaja" if "prodaja" in value else "izdavanje" if "izdavanje" in value else ""
    kind = ""
    for terms, result in [(('poslovn', 'lokal', 'magacin'), 'poslovni_prostor'),
                          (('placev', 'plac', 'zemljist'), 'plac'),
                          (('kuca', 'kuce'), 'kuca'), (('stanov', 'stan'), 'stan')]:
        if any(t in value for t in terms): kind = result; break
    return transaction, kind

def date_value(raw):
    from datetime import datetime
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", raw)
    if not m: return ""
    try: return datetime.strptime(m[0], "%d.%m.%Y").date().isoformat()
    except ValueError: return ""

def detail(html, url, source, search):
    soup = BeautifulSoup(html, "html.parser")
    rows = list(schema(soup))
    crumbs = breadcrumb(rows)
    category = next((c for c in crumbs if all(classify(c))), "")
    trans, kind = classify(category)
    if not trans or not kind:
        if source == "4zida": trans, kind = classify(urlsplit(url).path.split('/')[1])
        if not trans or not kind: raise ValueError("Missing listing category; refusing search-only classification")
    ad = Listing(source, urlsplit(url).path.split("/")[-1], canonical(url), text(soup.select_one("h1")), trans, kind, source_category=category)
    if (trans, kind) != (search["transaction"], search["property_type"]):
        ad.review_reasons.append("search_category_conflict")
    if source == "oglasi":
        ad.source_id = re.search(r"03-[0-9]+", url)[0]
        ad.description = text(soup.select_one('[itemprop="description"]'))
        for tr in soup.select("tr"):
            cells = tr.select("td")
            if len(cells) == 2 and text(cells[0]).endswith(":"):
                ad.fields[text(cells[0]).rstrip(":")] = text(cells[1])
        ad.location_raw = ad.fields.get("Lokacija", "")
        ad.rooms = ad.fields.get("Sobnost", "")
        ad.floor = ad.fields.get("Nivo u zgradi", "")
        ad.heating = ad.fields.get("Grejanje", "")
        ad.area_m2 = area(ad.fields.get("Kvadratura", "")) if kind != "plac" else None
        ad.plot_area_m2 = area(ad.fields.get("Površina zemljišta", ad.fields.get("Površina placa", "")))
        if kind == "plac": ad.plot_area_m2 = ad.plot_area_m2 or area(ad.fields.get("Kvadratura", ""))
        price = soup.select_one('[itemprop="price"]')
        ad.price_raw = text(price)
        ad.price = number(price.get("content"), machine=True) if price else None
        currency = soup.select_one('[itemprop="priceCurrency"]')
        ad.currency = currency.get("content", text(currency)) if currency else ""
        timer = soup.select_one("time[datetime]")
        ad.updated_at = timer.get("datetime", "") if timer else ""
        panel = next((h.find_parent(class_="panel") for h in soup.select("h3") if "Informacije o oglašivaču" in text(h)), None)
        if panel:
            name = panel.select_one(".panel-body > div:first-child")
            ad.advertiser = text(name)
    else:
        by_id = {r["@id"]: r for r in rows if "@id" in r and len(r) > 1}
        def resolve(value):
            return by_id.get(value.get("@id"), value) if isinstance(value, dict) else {}
        real = next((r for r in rows if has_type(r, "RealEstateListing")), {})
        offer = resolve(real.get("offers", {}))
        obj = resolve(real.get("itemOffered", real.get("mainEntity", offer.get("itemOffered", {}))))
        desc = soup.select_one('[test-data="rich-text-description"] .whitespace-normal')
        ad.description = text(desc) or real.get("description", "")
        ad.description_incomplete = desc is None
        if ad.description_incomplete: ad.review_reasons.append("description_summary_only")
        # Geographic breadcrumb belongs to this listing, unlike the publisher's address.
        ad.location_raw = ", ".join(c for c in crumbs[2:] if not re.search(r"stan|soba|kuca|prostor|zemljist|plac|magacin", norm(c)))
        ad.price = number(offer.get("price"), machine=True)
        ad.currency = offer.get("priceCurrency", "")
        ad.price_raw = str(offer.get("price", ""))
        measure = obj.get("area", obj.get("floorSize", {}))
        size = number(measure.get("value"), machine=True) if isinstance(measure, dict) and measure.get("unitCode") in ("MTK", "m2") else None
        if kind == "plac": ad.plot_area_m2 = size
        else: ad.area_m2 = size
        ad.rooms = str(obj.get("numberOfRooms", ""))
        address = obj.get("address", {})
        ad.address = address.get("streetAddress", "") if isinstance(address, dict) else str(address)
        seller = resolve(offer.get("seller", {}))
        ad.advertiser = seller.get("name", "")
        for label, attr in [('Sprat','floor'), ('Grejanje:','heating'), ('Površina placa','plot_area_m2')]:
            node = soup.find(string=lambda v: v and v.strip() == label)
            if node:
                container = node.parent.parent
                value = text(container.select_one('strong')) if label == 'Sprat' else text(container).replace(label,'').strip()
                if label == 'Površina placa':
                    measured = area(value)
                    if measured: ad.plot_area_m2 = measured
                else: setattr(ad, attr, value)
        ad.fields = {"amenities": obj.get("amenityFeature", []), "geo": obj.get("geo", {}), "business_function": offer.get("businessFunction", "")}
        updated = next((text(n.parent) for n in soup.find_all(string=re.compile("Oglas ažuriran:"))), "")
        ad.updated_at = date_value(updated)
        ad.source_id = urlsplit(url).path.rsplit("/", 1)[-1]
    if ad.area_m2 is None and kind != 'plac': ad.review_reasons.append('building_area_missing')
    if ad.plot_area_m2 is None and kind == 'plac': ad.review_reasons.append('plot_area_missing')
    title_area = area(ad.title)
    stated_area = ad.plot_area_m2 if kind == 'plac' else ad.area_m2
    if title_area and stated_area and abs(title_area-stated_area) > max(1,stated_area*0.02):
        ad.review_reasons.append('title_area_conflict')
    if not ad.description: raise ValueError("Missing description; parser needs attention")
    # Read units only within the listing, never financing widgets or navigation.
    content = norm(ad.title + " " + ad.description + " " + ad.price_raw)
    if trans == "prodaja": ad.price_basis = "total"
    if trans == "izdavanje" and re.search(r"(?:po osobi|/osob)", content): ad.price_basis = "per_person"
    elif trans == "izdavanje" and re.search(r"(?:dnevno|po danu|na dan|/dan)", content): ad.price_basis = "daily"
    elif trans == "izdavanje" and re.search(r"(?:mesecno|mjesecno|/mesec|mesecna (?:cena|zakupnina))", content): ad.price_basis = "monthly"
    if trans == 'izdavanje' and ad.price_basis != 'unknown':
        ad.review_reasons.append('rental_price_period_from_text')
    if re.search(r"(?:cena|price).{0,30}(?:po m2|/m2|/m²)", content):
        ad.price_basis = 'unknown'
        ad.review_reasons.append('price_per_m2_requires_review')
    code = re.search(r"(?:agencijska šifra|agencijski id)\s*:\s*([A-Za-z0-9-]+)", ad.description, re.I)
    if code: ad.agency_id = code[1]
    return ad.validate()
