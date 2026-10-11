import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from .model import now, Listing, LOCATIONS

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
          url TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
          transaction_type TEXT NOT NULL, property_type TEXT NOT NULL,
          payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
          fetched_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'observed', unavailable_at TEXT);
        CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, url TEXT NOT NULL,
          recorded_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, source TEXT NOT NULL,
          search_url TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
          status TEXT NOT NULL, details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS photo_cache (url TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, fingerprint TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS listing_categories ON listings(transaction_type,property_type);
        """)

        columns={r['name'] for r in self.db.execute('PRAGMA table_info(listings)')}
        with self.db:
            for column in ('checked_at','price_changed_at'):
                if column not in columns:self.db.execute(f'ALTER TABLE listings ADD COLUMN {column} TEXT')
            self.db.execute("CREATE TABLE IF NOT EXISTS archived_listings (url TEXT PRIMARY KEY, archived_at TEXT NOT NULL, reason TEXT NOT NULL, record TEXT NOT NULL)")

    def known(self,url):
        return bool(self.db.execute('SELECT 1 FROM listings WHERE url=? UNION ALL SELECT 1 FROM archived_listings WHERE url=?',(url,url)).fetchone())

    def backup(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        target=sqlite3.connect(path)
        try:self.db.backup(target)
        finally:target.close()

    def checked(self,url):
        with self.db:self.db.execute('UPDATE listings SET checked_at=? WHERE url=?',(now(),url))

    def due(self,hours=None):
        from zoneinfo import ZoneInfo
        cutoff=((datetime.now(ZoneInfo('Europe/Belgrade')).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)) if hours is None else datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
        return [dict(r) for r in self.db.execute("SELECT * FROM listings WHERE status='observed' AND COALESCE(checked_at,'')<? ORDER BY COALESCE(checked_at,''),first_seen",(cutoff,))]

    def expire(self,stamp=None,eligible_urls=None):
        import calendar
        stamp=stamp or datetime.now(timezone.utc)
        month_index=stamp.year*12+stamp.month-1-6
        year,month=divmod(month_index,12);month+=1
        cutoff=stamp.replace(year=year,month=month,day=min(stamp.day,calendar.monthrange(year,month)[1]))
        count=0
        with self.db:
            for row in self.db.execute("SELECT * FROM listings WHERE status='observed'").fetchall():
                if eligible_urls is not None and row['url'] not in eligible_urls:continue
                data=json.loads(row['payload'])
                dates=[row['first_seen'],row['price_changed_at']]
                # Only explicitly published ISO dates can establish an older publication.
                if data.get('published_at'):
                    try:
                        published=datetime.fromisoformat(data['published_at'].replace('Z','+00:00'))
                        if published.tzinfo and published<=stamp:dates[0]=published.isoformat()
                    except ValueError:pass
                anchor=max(datetime.fromisoformat(value) for value in dates if value)
                # Check price after cutoff before retiring an old listing; network failures retain it.
                checked=datetime.fromisoformat(row['checked_at']) if row['checked_at'] else None
                if anchor<cutoff and checked and checked>=cutoff:
                    self.db.execute('INSERT OR REPLACE INTO archived_listings VALUES(?,?,?,?)',(row['url'],stamp.isoformat(),'expired_without_price_change',json.dumps(dict(row),ensure_ascii=False)))
                    self.db.execute('DELETE FROM listings WHERE url=?',(row['url'],));count+=1
        return count

    def fresh(self, url, hours):
        row = self.db.execute("SELECT fetched_at,status FROM listings WHERE url=?", (url,)).fetchone()
        return bool(row and row["status"] == "observed" and datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - timedelta(hours=hours))

    def seen(self, url):
        with self.db: self.db.execute("UPDATE listings SET last_seen=? WHERE url=?", (now(), url))

    def unavailable(self, url):
        with self.db: self.db.execute("UPDATE listings SET status='unavailable', unavailable_at=?, checked_at=? WHERE url=?", (now(), now(), url))

    def save(self, ad):
        stamp = now()
        payload = json.dumps(ad.to_dict(), ensure_ascii=False, sort_keys=True)
        old = self.db.execute("SELECT payload,price_changed_at FROM listings WHERE url=?", (ad.url,)).fetchone()
        previous=json.loads(old['payload']) if old else {}
        price_changed=old is not None and previous.get('price') is not None and ad.price is not None and (previous.get('price'),previous.get('currency'),previous.get('price_basis'))!=(ad.price,ad.currency,ad.price_basis)
        price_stamp=stamp if price_changed else old['price_changed_at'] if old else None
        with self.db:
            if old is None or old[0] != payload:
                self.db.execute("INSERT INTO versions(url,recorded_at,payload) VALUES(?,?,?)", (ad.url, stamp, payload))
            self.db.execute("""INSERT INTO listings(url,source,source_id,transaction_type,property_type,payload,first_seen,last_seen,fetched_at,status,unavailable_at) VALUES(?,?,?,?,?,?,?,?,?,'observed',NULL)
                ON CONFLICT(url) DO UPDATE SET payload=excluded.payload,
                transaction_type=excluded.transaction_type,property_type=excluded.property_type,
                last_seen=excluded.last_seen,fetched_at=excluded.fetched_at,status='observed',unavailable_at=NULL""",
                (ad.url, ad.source, ad.source_id, ad.transaction, ad.property_type, payload, stamp, stamp, stamp))
            self.db.execute('UPDATE listings SET checked_at=?,price_changed_at=? WHERE url=?',(stamp,price_stamp,ad.url))

    def record(self, source, search_url, started, status, details):
        with self.db: self.db.execute("INSERT INTO runs(source,search_url,started_at,finished_at,status,details) VALUES(?,?,?,?,?,?)", (source, search_url, started, now(), status, json.dumps(details, ensure_ascii=False)))

    def listings(self, transaction=None, property_type=None, location=None, include_outside=False, active_only=False):
        result = []
        for row in self.db.execute("SELECT * FROM listings ORDER BY first_seen DESC,url"):
            if active_only and row['status']!='observed':continue
            if transaction and row['transaction_type'] != transaction: continue
            if property_type and row['property_type'] != property_type: continue
            data = json.loads(row['payload'])
            # Apply current scope and price defaults to old records without falsifying fetch times.
            ad = Listing(**{key: value for key,value in data.items() if key in Listing.__dataclass_fields__})
            if 'price_per_m2_requires_review' not in ad.review_reasons:
                from .model import price_basis
                ad.price_basis, ad.price_basis_method = price_basis(ad.transaction, ad.title, ad.description, ad.price_raw)
            ad = ad.validate().to_dict()
            if not include_outside and (ad['location'] not in LOCATIONS or 'title_location_conflict' in ad['review_reasons']): continue
            if location and ad['location'] != location: continue
            ad.update({key: row[key] for key in ('first_seen','last_seen','fetched_at','status','unavailable_at')})
            result.append(ad)
        return result

    def photo_cached(self, url, hours=24):
        row = self.db.execute('SELECT * FROM photo_cache WHERE url=?',(url,)).fetchone()
        if row and datetime.fromisoformat(row['fetched_at']) > datetime.now(timezone.utc)-timedelta(hours=hours):
            return json.loads(row['fingerprint'])
        return None

    def save_photo(self, url, fingerprint):
        with self.db: self.db.execute('INSERT OR REPLACE INTO photo_cache VALUES(?,?,?)',(url,now(),json.dumps(fingerprint)))

    def status(self):
        return [dict(r) | {'details': json.loads(r['details'])} for r in self.db.execute("SELECT * FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY source,search_url) ORDER BY source,search_url")]

    def close(self): self.db.close()
