from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

TRANSACTIONS = ("prodaja", "izdavanje")
PROPERTY_TYPES = ("stan", "kuca", "poslovni_prostor", "plac")
LOCATIONS = ("Petrovaradin", "Sremska Kamenica", "Sremski Karlovci")
CYRILLIC = str.maketrans(dict(zip("абвгдђежзијклљмнњопрстћуфхцчџш", ["a","b","v","g","d","dj","e","z","z","i","j","k","l","lj","m","n","nj","o","p","r","s","t","c","u","f","h","c","c","dz","s"])))

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def norm(value):
    return " ".join(unicodedata.normalize("NFKD", str(value).lower().translate(CYRILLIC).replace("đ", "dj")).encode("ascii", "ignore").decode().split())

def canonical(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))

def number(value, machine=False):
    if value is None or value == "": return None
    if isinstance(value, (int, float)): return float(value)
    raw = re.sub(r"[^0-9.,-]", "", str(value))
    if not raw: return None
    if not machine:
        if "," in raw: raw = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", raw): raw = raw.replace(".", "")
    try: return float(raw)
    except ValueError: return None

def area(value):
    match = re.search(r"([0-9.,]+)\s*(m2|m²|ar(?:a)?|ha)\b", str(value), re.I)
    # Unicode square sign does not create a word boundary at end.
    if not match: match = re.search(r"([0-9.,]+)\s*(m²)", str(value), re.I)
    if not match: return None
    n = number(match[1])
    return n * {"ar": 100, "ara": 100, "ha": 10000}.get(match[2].lower(), 1) if n is not None and n > 0 else None

def local_location(raw):
    value = norm(raw)
    matches = [name for name in LOCATIONS if re.search(r"\b" + re.escape(norm(name)) + r"\b", value)]
    return matches[0] if len(matches) == 1 else ""


def title_locations(title):
    value=norm(title)
    patterns={'Petrovaradin':r'\bpetrovaradin(?:u|a)?\b',
              'Sremska Kamenica':r'\bsremsk(?:a|oj|u|e) kamenic(?:a|i|u|e)\b',
              'Sremski Karlovci':r'\bsremsk(?:i|im|ih|e) karlov(?:ci|cima|aca|ce)\b'}
    return {name for name,pattern in patterns.items() if re.search(pattern,value)}


def price_basis(transaction, title="", description="", price_raw=""):
    if transaction == "prodaja": return "total", "transaction_default"
    # Monthly rent is the agreed default. Explicit short-term/person pricing overrides it.
    content = norm(title + " " + description + " " + price_raw)
    for pattern, basis in [(r"po osobi|/osob", "per_person"),
                           (r"stan na dan|izdavanje na dan|izdaje se na dan|dnevni najam|po danu|/dan\b|\bdnevno\b", "daily")]:
        for match in re.finditer(pattern, content):
            prefix = content[max(0,match.start()-35):match.start()]
            if re.search(r"\b(?:ne|nije|bez)\b[^.,;]*$", prefix): continue
            return basis, "explicit_text"
    return "monthly", "transaction_default"


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str
    transaction: str
    property_type: str
    description: str = ""
    location_raw: str = ""
    location: str = ""
    address: str = ""
    price: float | None = None
    currency: str = ""
    price_basis: str = "unknown"
    price_raw: str = ""
    area_m2: float | None = None
    plot_area_m2: float | None = None
    rooms: str = ""
    floor: str = ""
    heating: str = ""
    advertiser: str = ""
    agency_id: str = ""
    updated_at: str = ""
    published_at: str = ""
    source_category: str = ""
    fields: dict = field(default_factory=dict)
    review_reasons: list = field(default_factory=list)
    description_incomplete: bool = False
    photos: list = field(default_factory=list)
    price_basis_method: str = ""


    def to_dict(self): return asdict(self)

    def validate(self):
        if self.transaction not in TRANSACTIONS or self.property_type not in PROPERTY_TYPES:
            raise ValueError("Unknown transaction/property type")
        if not self.title: raise ValueError("Missing listing title")
        if not self.location_raw: self.review_reasons.append("location_missing")
        self.location = local_location(self.location_raw)
        stated_places=title_locations(self.title)
        if self.location and stated_places and self.location not in stated_places:
            self.review_reasons.append('title_location_conflict')
        self.review_reasons = [r for r in self.review_reasons if r not in ("location_not_confirmed", "rental_price_period_unknown", "rental_price_period_from_text")]
        if not self.location:
            self.review_reasons.append("location_not_confirmed")
        if self.price_basis == "unknown" and "price_per_m2_requires_review" not in self.review_reasons:
            self.price_basis, self.price_basis_method = price_basis(self.transaction, self.title, self.description, self.price_raw)
        if self.price is not None and self.price <= 0:
            self.price = None
            self.review_reasons.append("price_invalid")
        self.review_reasons = sorted(set(self.review_reasons))
        return self
