# Nekretnine — Petrovaradin i okolina

Python 3.10+ sakupljač nekretnina sa SQLite istorijom, fotografskim otiscima i grupisanim prikazom. Aktivna grana: `fix/nekretnine-001`.

## Pokretanje

```powershell
cd D:\PycharmProjects\nekretnine
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py collect
.\venv\Scripts\python.exe main.py status
.\venv\Scripts\python.exe main.py deduplicate
.\venv\Scripts\python.exe main.py export
.\venv\Scripts\python.exe main.py export --format csv
.\venv\Scripts\python.exe main.py candidates
.\venv\Scripts\python.exe main.py report
```

Sve komande, redom, bez instaliranja rasporeda:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-collector.ps1
```

Baza i logovi su u `data/` i `logs/`. Putanje su vezane za projekat, ne trenutni terminal. `--refresh` obnavlja detalje; podrazumevani keš je 24 sata. `--max-details` i `--max-pages` važe po pretrazi. Ograničen prolaz daje status `partial` i kod 2. Kod 0 znači da nema detektovanih grešaka/limita u odabranim pretragama; nije garancija svih oglasa sa interneta. Ctrl+C završava sa kodom 130 i čuva već upisane podatke.

## Lokalni obuhvat i kategorije

Dozvoljena mesta: **Petrovaradin, Sremska Kamenica i Sremski Karlovci**. Ukupno je podešeno 45 pretraga: Oglasi.rs po sedam kategorija za svako mesto; 4zida po osam. Osnovne prodajne putanje za nova mesta proverene su direktnim HTTP pristupom; ostale dele isti kategorijski obrazac i još zahtevaju potpun probni prolaz.

`prodaja` / `izdavanje` i `stan` / `kuca` / `poslovni_prostor` / `plac` su nezavisni filteri. Oglasi.rs nema potvrđenu posebnu kategoriju izdavanja placeva; 4zida ima. Ostali istraženi izvori su samo kandidati u `additional_sources`, bez adaptera.

```powershell
.\venv\Scripts\python.exe main.py collect --source oglasi --location "Petrovaradin" --transaction izdavanje --type stan --max-details 3 --max-pages 1
.\venv\Scripts\python.exe main.py export --location "Sremska Kamenica" --transaction prodaja --type kuca
```

Lokacija mora biti navedena u polju lokacije ili geografskoj breadcrumb putanji samog oglasa. Naziv „Novi Sad”, naslov, opis, sedište agencije ili sama stranica pretrage nisu dovoljni. Neslaganje izričito navedenog mesta u naslovu i izvornog polja lokacije nosi `title_location_conflict` i izostavlja se iz lokalnog izvoza do provere. Nepoznata, višeznačna i druga mesta preskaču se pri sakupljanju, uz brojač `outside_area`. Stari zapisi ostaju u bazi, ali se van dozvoljenog obuhvata ne izvoze i ne prikazuju. Ćirilica i latinica se normalizuju. Nema automatskog zaključivanja mesta samo iz mikrolokacije bez eksplicitnog roditeljskog mesta.

## Cene i površine

Prodajna cena je ukupna cena nekretnine (`total`), a izdavanje podrazumevano mesečna zakupnina (`monthly`), prema dogovorenom pravilu. `price_basis_method=transaction_default` jasno označava ovu pretpostavku. Izričito navedeni stan na dan/dnevni najam i cena po osobi imaju `daily` / `per_person` i ne grupišu se sa redovnom mesečnom zakupninom. Negirano „ne izdaje se stan na dan” ne menja mesečni osnov. Izričita jedinica po m² u izvornom polju cene ostaje za proveru; ne predstavlja se kao ukupna cena.

`area_m2` je površina objekta, a `plot_area_m2` površina zemljišta. Kuća može imati obe vrednosti; plac koristi samo površinu zemljišta. Ari/hektari se pretvaraju u m². Nepostojeća polja ostaju prazna. Neslaganje kvadrature naslova i strukturiranih podataka nosi `title_area_conflict` i sprečava automatsko grupisanje.

## Prepoznavanje istih nekretnina

Jednaka cena i kvadratura same nisu dokaz. Poređenje traži isto mesto, vrstu ponude, tip nekretnine, valutu i osnov cene, kao i površinu uz toleranciju od 2%, odnosno najmanje 1 m². Poznati različiti sprat, sobnost, adresa, površina placa uz kuću ili različite šifre iste agencije sprečavaju grupisanje.

Automatska grupa traži jedan od obrazaca:

1. Isti normalizovani oglašivač i njegova ista agencijska šifra, uz saglasnu površinu i bez velikog cenovnog odstupanja.
2. Najmanje dve različite podudarne fotografije, saglasnu površinu, cenu unutar 10% i dodatno saglasnu poznatu sobnost/sprat ili vrlo sličan pun opis.
3. Gotovo isti pun opis (najmanje 200 znakova, sličnost 97%), saglasnu površinu/cenu i saglasnu poznatu sobnost i sprat.

Dokazi i odstupanja čuvaju se u `matching_evidence`. Slabija podudaranja ostaju u `candidates` za pregled. Agencijska šifra bez istog oglašivača nije dovoljan dokaz. Jedna fotografija nije dovoljna sama. Pravila se primenjuju i na više objava istog sajta. Svaki par članova grupe mora proći pravila; nema lančanog spajanja A–B–C ako su A i C u konfliktu.

Ovo je konzervativno prepoznavanje, ne potvrda identiteta vlasnika ili nekretnine. Zajedničke fotografije/renderi i šablonski opisi novogradnje ostaju mogući izvori greške. Oglasi bez dovoljno dokaza prikazuju se kao zasebne grupe. Trenutni mali probni uzorak nije merilo preciznosti na celom tržištu.

Fotografije se uzimaju iz galerije oglasa, ne iz logotipa agencije ili navigacije. Prvih šest po oglasu se podrazumevano obrađuje u memoriji. Čuvaju se URL, SHA-256, dHash i aHash, dimenzije i 24-časovni keš otisaka; originalne datoteke se ne skladište. Vizuelno poređenje dopušta male promene kompresije/dimenzija, ali ne garantuje prepoznavanje velikih kropova i vodenih žigova. Male/jednobojne slike se odbacuju; ponovljena ista fotografija u galeriji broji se jednom. U `sources.json` postaviti `photo_hash_limit: 0` za isključivanje preuzimanja fotografija. Greške fotografija prikazuju se u `photo_errors` i logu, bez gubitka važećeg tekstualnog oglasa.

## Grupisani izlazi

- `export`: `data/nekretnine.json`, jedna stavka po grupi, sa svim originalima u `listings` i linkovima/cenama u `sources`.
- `export --flat`: kompatibilan ravan JSON pojedinačnih oglasa.
- `export --format csv`: jedan red po izvornom oglasu, zajednički `group_id` i `group_size`; UTF-8 BOM i separator `;`, neutralizovane formule.
- `deduplicate`: `data/nekretnine-grupe.json`, grupisani snimak bez menjanja izvornih zapisa.
- `candidates`: `data/nekretnine-duplikati.json`, svi prepoznati parovi sa `automatic` i `review_required`.
- `report`: `data/nekretnine-pregled.html`, kartica po grupi, svi originalni oglasi i njihove cene, filteri za mesta i kategorije.

`price_min` i `price_max` pokazuju razliku cena unutar grupe. Glavna polja grupe dolaze iz najpotpunijeg člana; svaki original zadržava svoje podatke. `group_id` je deterministički za isti skup URL-ova i menja se ako se promeni članstvo grupe; nije trajni identifikator fizičke nekretnine. Stari zapisi se pri čitanju usklađuju sa novim lokalnim/mesecnim pravilima bez izmišljanja novog datuma preuzimanja. Fotografije starih zapisa dopunjuju se tek nakon `collect --refresh`.

## Istorija, dostupnost i pristup

SQLite čuva izvorne objave, verzije, pokretanja i keš fotografija. Promena istog URL-a čuva novu verziju, uz nepromenjen prvi pronalazak. `first_seen` i `last_seen` nisu datum objave. Status `observed` znači viđen oglas; HTTP 404/410 znači `unavailable`, ne „prodato”. Nestanak sa liste ili greška izvora ne menja dostupnost starih oglasa. Poznati URL-ovi koji nestanu sa lista još nemaju poseban periodični obilazak.

HTML i fotografski zahtevi poštuju `robots.txt`, crawl delay i razmak zahteva. Nema zaobilaženja CAPTCHA. Fotografija ima limit 8 MiB i 20 megapiksela. Tehnički pristup ne potvrđuje pravo distribucije sadržaja; na 4zida je navedeno ograničenje preuzimanja osim za lične potrebe bez njihove dozvole. Pre javne/komercijalne upotrebe urediti dozvolu/feed sa izvorom.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Skripta ažurira izvoze i pregled i kod delimično uspešnog prolaza. Raspored nije instaliran. Nije napravljen javni sajt niti je nešto objavljeno na GitHub-u.

## Pokretanje i nadgledanje (fix/nekretnine-002)

U PowerShell terminalu:

```powershell
cd D:\PycharmProjects\nekretnine
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-collector.ps1
```

U drugom terminalu pratite napredak:

```powershell
cd D:\PycharmProjects\nekretnine
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\watch-collector.ps1
```

`-Once` daje jedan prikaz, a `-Interval 3` menja interval čitanja. Alternativa je `venv\Scripts\python.exe main.py watch`; `main.py status --live` daje jedan trenutni prikaz. Ctrl+C u monitoru zatvara samo monitor. Ctrl+C u sakupljaču prekida prolaz i ostavlja sačuvane podatke.

Prikaz sadrži približan procenat, završene/ukupne pretrage, proteklo vreme, procenjeno preostalo vreme, obrađene oglase, sačuvane oglase, preskočene sveže oglase i greške. Napredak se zapisuje na svakih 10 sekundi, i dok traje mrežni zahtev, u `data/nekretnine.progress.json`. Sadrži i PID, aktivni URL, pojedinačne pretrage i putanju loga. Monitor prijavljuje ugašen proces i zastareo prikaz.

Procena koristi obim ranijih neograničenih prolaza bez grešaka, broj oglasa koji sajt objavljuje i novootkrivene stranice. Bez istorije počinje sa grubom pretpostavkom; procena vremena pojavljuje se posle 30 sekundi rada. Procenat može da se smanji kada se otkrije dodatni obim. Brzina keširanih oglasa i mrežni zastoji utiču na tačnost procene. 100% znači da je završen pokušaj svih izabranih pretraga; proverite greške i broj pretraga sa problemom. Ograničen ili delimičan prolaz nije potpuna kolekcija.

Drugi sakupljač nad istom bazom odbija se OS zaključavanjem (izlazni kod 3); zaključavanje se oslobađa pri završetku procesa. Nemojte brisati `.collect.lock` dok proces radi. Za ponovnu obradu svih poznatih oglasa prosledite `-Refresh` skripti za pokretanje; normalno pokretanje preskače sveže oglase. Posle sakupljanja skripta osvežava JSON, CSV, predloge duplikata i HTML pregled.

Proces pokrenut pre ove verzije nema prikaz napretka ni zaključavanje: sačekajte njegov završetak pre novog pokretanja. Njegov rad možete pratiti preko `Get-Content <putanja-loga> -Tail 20 -Wait`. Novi monitor važi od sledećeg pokretanja.

Testovi pokrivaju stvarne HTML uzorke, grupisanje i razlike između stanova, fotografije pri kompresiji/promeni dimenzija, lokalni filter, cene, istoriju i očuvanje svih izvornih linkova. Raspored nije instaliran i sadržaj nije javno objavljen.
