# Nekretnine — Petrovaradin

Python 3.10+ sakupljač po obrascu projekta `oglasi`, sa zasebnim modelom i bazom za nekretnine.

## Pokretanje

```powershell
cd D:\PycharmProjects\nekretnine
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py collect
.\venv\Scripts\python.exe main.py status
.\venv\Scripts\python.exe main.py export
.\venv\Scripts\python.exe main.py export --format csv
.\venv\Scripts\python.exe main.py candidates
.\venv\Scripts\python.exe main.py report
```

`main.py` bez argumenata prikazuje pomoć. Python okruženje `venv` je lokalno; nije deo izvornog koda. Putanje baze, izvora, izvoza i logova vezane su za koren projekta.

Primer ograničenog prolaza:

```powershell
.\venv\Scripts\python.exe main.py collect --source oglasi --transaction izdavanje --type stan --max-details 3 --max-pages 1
.\venv\Scripts\python.exe main.py export --transaction prodaja --type kuca
```

Tipovi: `stan`, `kuca`, `poslovni_prostor`, `plac`. Ponude: `prodaja`, `izdavanje`. Filteri su nezavisni i rade na sakupljanju, izvozu, pregledu i kandidatima za duplikate. `--refresh` preskače keš; inače se detalji osvežavaju nakon 24 sata, a ponovno pronalaženje u listi ažurira `last_seen`.

`--max-details` i `--max-pages` važe po pretrazi, ne globalno. Izlazni kod 0 znači da su odabrane pretrage obrađene bez detektovanih problema, 2 znači delimičan rezultat/limit, 130 prekid. Limit nije potpuna pokrivenost. Ctrl+C završava prikupljanje sa kodom 130; već sačuvani oglasi ostaju u bazi.

## Izvori

- Oglasi.rs: prodaja i izdavanje stanova, kuća i poslovnih prostora; prodaja placeva. Putanja za izdavanje poslovnog prostora razlikuje se od prodajne.
- 4zida: prodaja i izdavanje sva četiri tipa, uključujući placeve.
- Ostali istraženi izvori navedeni su u `sources.json` kao `additional_sources`, bez implementiranih adaptera: Halo oglasi, Nekretnine.rs, City Expert, NadjiDom, NS Group, Solis. Ne predstavljaju se kao aktivni izvori.

Obe implementacije proverene su direktnim HTTP pristupom 10.10.2026. i ograničenim prolazom kroz svih 15 pretraga. HTML uzorci u testovima predstavljaju snimke, ne aktuelnu ponudu. Za Oglasi.rs nije potvrđena kategorija izdavanja placeva.

HTTP pristup poštuje `robots.txt`, razmak zahteva i crawl delay. Greške, blokade i neprepoznata prazna lista prijavljuju se kao `partial`. Nema zaobilaženja CAPTCHA ili pristupa nalozima. Na 4zida stranici stoji ograničenje preuzimanja sadržaja bez dozvole osim za lične potrebe posetilaca; tehnički funkcionalan adapter ne potvrđuje dozvolu za javnu/komercijalnu distribuciju. Pre takve upotrebe urediti dozvolu/feed sa izvorom.

## Model nekretnine

`transaction` i `property_type` dolaze iz kategorije samog oglasa, ne iz ključnih reči u opisu. Izvorna kategorija ostaje u `source_category`. Oglas iz druge kategorije dobija `search_category_conflict`.

Čuvaju se naslov, opis, URL i ID izvora, oglašivač, agencijska šifra gde postoji, izvorna lokacija, potvrđena lokacija Petrovaradin, cena, valuta i osnova cene, površina objekta i zasebna površina placa, sobnost, sprat, grejanje i datum ažuriranja gde ih izvor objavljuje. Nedostajuća polja ostaju prazna. 4zida schema reference se razrešavaju po ID-u; adresa platforme se ne koristi kao adresa nekretnine. Opis se uzima iz oglasa, a ne iz navigacije ili preporučenih oglasa.

Plac ima `plot_area_m2`; kuća može imati i `area_m2` i `plot_area_m2`. Ari i hektari se pretvaraju u m² uz očuvana izvorna polja. Ne izvodi se površina placa iz opisa kuće. Kategorija „kuća” ostaje kuća i kada opis pominje rušenje; precizniji podtipovi trenutno ostaju u izvornim poljima/opisu.

Cena prodaje ima osnovu `total` (osim kada je navedena cena po m²), a izdavanje `unknown` dok tekst oglasa izričito ne navede mesečnu, dnevnu ili cenu po osobi. Nepoznat period nosi `rental_price_period_unknown`. Prepoznavanje perioda u tekstu nosi `rental_price_period_from_text` i zahteva proveru; ne čita se iz kreditnih rata ili navigacije. Oglas sa naznakom cene po m² dobija oznaku za proveru. Cena i površina iz strukturiranih podataka imaju prednost; neslaganje sa površinom u naslovu dobija `title_area_conflict`.

Lokacija mora biti potvrđena u polju lokacije ili breadcrumb putanji oglasa. Sama lista za Petrovaradin nije potvrda. Nepotvrđeni oglasi ostaju za proveru sa `location_not_confirmed`; još nema geografskog poligona ni automatskog mapiranja mikrolokacija bez eksplicitnog Petrovaradina. Izvoz uključuje i zapise za proveru; koristiti `review_reasons` i `location` pri prikazu na odredišnoj platformi.

## Baza, istorija i dostupnost

`data/nekretnine.sqlite3` ima tabele `listings`, `versions` i `runs`. Isti izvorni URL se ažurira bez novog oglasa. Promena sadržaja/cene pravi novu verziju; prvi pronalazak ostaje sačuvan. `first_seen` i `last_seen` nisu datum objavljivanja. `updated_at` je datum koji prikazuje izvor; `published_at` ostaje prazan ako nije objavljen.

Status `observed` znači da je oglas viđen, bez tvrdnje da je nekretnina još dostupna. Potvrđeni HTTP 404/410 označava poznati oglas kao `unavailable`; ne znači „prodato”. Nestanak iz liste, delimičan prolaz ili pad sajta ne menjaju status starih oglasa. Poznati URL-ovi koji nestanu iz liste još se ne proveravaju zasebnim periodičnim obilaskom.

`candidates` daje konzervativne predloge duplikata između izvora: ista ponuda i tip, potvrđena ista lokacija, slična cena/površina i vrlo sličan opis ili ista agencijska šifra i oglašivač. Rezultat zahteva pregled i ne menja bazu. Ne spaja različite stanove u istoj novogradnji samo zbog cene i kvadrature. JSON/CSV i pregled su po izvornoj objavi, ne po jedinstvenoj fizičkoj nekretnini.

## Izlazi i provera

- `data/nekretnine.json`: pun JSON sa oznakama za proveru i vremenima pronalaska.
- `data/nekretnine.csv`: CSV za Excel, UTF-8 BOM, separator `;`, neutralizovane formule u tekstu.
- `data/nekretnine-pregled.html`: samostalan lokalni pregled sa pretragom i filterima.
- `data/nekretnine-duplikati.json`: kandidati za pregled.
- `logs/collect-DATUM-VREME-PID.log`: zahtevi, ishodi i problemi svakog prolaza.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-collector.ps1
```

Skripta ažurira izvoze i pregled i kod delimično uspešnog prolaza. Raspored nije instaliran. Nije napravljen javni sajt niti je nešto objavljeno na GitHub-u.
