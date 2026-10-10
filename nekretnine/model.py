from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

TRANSACTIONS = ("prodaja", "izdavanje")
PROPERTY_TYPES = ("stan", "kuca", "poslovni_prostor", "plac")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def norm(value):
    return " ".join(unicodedata.normalize("NFKD", str(value).lower()).encode("ascii", "ignore").decode().split())

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

    def to_dict(self): return asdict(self)

    def validate(self):
        if self.transaction not in TRANSACTIONS or self.property_type not in PROPERTY_TYPES:
            raise ValueError("Unknown transaction/property type")
        if not self.title: raise ValueError("Missing listing title")
        if not self.location_raw: self.review_reasons.append("location_missing")
        if re.search(r"\bpetrovaradin\b", norm(self.location_raw)):
            self.location = "Petrovaradin"
        else:
            self.location = ""
            self.review_reasons.append("location_not_confirmed")
        if self.transaction == "izdavanje" and self.price_basis == "unknown":
            self.review_reasons.append("rental_price_period_unknown")
        if self.price is not None and self.price <= 0:
            self.price = None
            self.review_reasons.append("price_invalid")
        self.review_reasons = sorted(set(self.review_reasons))
        return self
