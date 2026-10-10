import json
import tempfile
import unittest
from pathlib import Path
from nekretnine.model import Listing, number, area
from nekretnine.parsers import detail, listing_page
from nekretnine.store import Store
from nekretnine.collector import collect
from nekretnine.export import candidates, export, report

FIXTURES=Path(__file__).parent/'fixtures'

class ParserTests(unittest.TestCase):
    def parse_fixture(self, source):
        searches=json.loads((FIXTURES.parents[1]/'sources.json').read_text())['sources']
        search=next(s['searches'][0] for s in searches if s['id']==source)
        links,pages,empty=listing_page((FIXTURES/(source+'-listing.html')).read_text(encoding='utf-8'),search['url'],source)
        self.assertTrue(links); self.assertTrue(pages); self.assertFalse(empty)
        return detail((FIXTURES/(source+'-detail.html')).read_text(encoding='utf-8'),links[0],source,search)

    def test_oglasi_real_fixture(self):
        ad=self.parse_fixture('oglasi')
        self.assertEqual((ad.transaction,ad.property_type,ad.location),('prodaja','stan','Petrovaradin'))
        self.assertEqual(ad.price,81090); self.assertEqual(ad.area_m2,30)
        self.assertIn('BERZA',ad.advertiser); self.assertEqual(ad.agency_id,'1008009')

    def test_4zida_references_not_publisher_address(self):
        ad=self.parse_fixture('4zida')
        self.assertEqual(ad.price,226500); self.assertEqual(ad.area_m2,101)
        self.assertEqual(ad.rooms,'4'); self.assertEqual(ad.location,'Petrovaradin')
        self.assertNotIn('Subotica',ad.location_raw)

    def test_all_categories_are_independent(self):
        for trans in ('prodaja','izdavanje'):
            for kind,category in [('stan','stanova'),('kuca','kuca'),('poslovni_prostor','poslovnog prostora'),('plac','placeva')]:
                data={'@type':'BreadcrumbList','itemListElement':[{'name':trans+' '+category}]}
                markup='<h1>Oglas</h1><script type="application/ld+json">'+json.dumps(data)+'</script><table><tr><td>Lokacija:</td><td>Petrovaradin</td></tr><tr><td>Kvadratura:</td><td>12 ar</td></tr><tr><td>Površina placa:</td><td>5 ar</td></tr></table><div itemprop="description">Opis nekretnine</div><span itemprop="price" content="1000.00">1.000,00</span>'
                ad=detail(markup,'https://www.oglasi.rs/oglas/03-123/oglas','oglasi',{'transaction':trans,'property_type':kind})
                self.assertEqual((ad.transaction,ad.property_type),(trans,kind))
                self.assertEqual(ad.plot_area_m2,500)
                self.assertEqual(ad.area_m2,None if kind=='plac' else 1200)
                self.assertEqual(ad.price_basis,'unknown' if trans=='izdavanje' else 'total')

    def test_4zida_ignores_recommendations_from_other_categories(self):
        url='https://www.4zida.rs/prodaja-stanova/petrovaradin-gradske-lokacije-novi-sad'
        markup='<a href="/izdavanje-kuca/beograd/kuca/68bad4339f50b40bc00a3654">Preporuka</a>'
        self.assertEqual(listing_page(markup,url,'4zida')[0],[])

    def test_missing_category_is_not_inferred_from_search(self):
        with self.assertRaises(ValueError):
            detail('<h1>Oglas</h1><div itemprop="description">Petrovaradin</div>','https://www.oglasi.rs/oglas/03-1/ad','oglasi',{'transaction':'prodaja','property_type':'stan'})

    def test_house_breadcrumb_has_no_final_room_type(self):
        url='https://www.4zida.rs/prodaja-kuca/petrovaradin-gradske-lokacije-novi-sad/kuca/68bad4339f50b40bc00a3654'
        ad=detail((FIXTURES/'4zida-house.html').read_text(encoding='utf-8'),url,'4zida',{'transaction':'prodaja','property_type':'kuca'})
        self.assertEqual(ad.location,'Petrovaradin')
        self.assertEqual(ad.area_m2,360)

    def test_units_and_prices(self):
        self.assertEqual(number('81.090,00'),81090)
        self.assertEqual(number('81090.00',machine=True),81090)
        self.assertEqual(area('1,5 ha'),15000)
        self.assertEqual(area('29m2'),29)
        self.assertIsNone(area('0m2'))

class StoreTests(unittest.TestCase):
    def test_upsert_history_unavailable_and_return(self):
        with tempfile.TemporaryDirectory() as d:
            db=Store(Path(d)/'db.sqlite3')
            ad=Listing('test','1','https://test/ad','Stan','prodaja','stan',location_raw='Petrovaradin',price=100).validate()
            db.save(ad); db.save(ad)
            self.assertEqual(db.db.execute('SELECT count(*) FROM versions').fetchone()[0],1)
            ad.price=90; db.save(ad)
            self.assertEqual(db.db.execute('SELECT count(*) FROM versions').fetchone()[0],2)
            db.unavailable(ad.url); self.assertFalse(db.fresh(ad.url,24))
            db.save(ad); self.assertEqual(db.listings()[0]['status'],'observed')
            self.assertEqual(len(db.listings(transaction='izdavanje')),0)
            db.close()

    def test_failed_source_never_marks_old_listing_unavailable(self):
        class Fake:
            def get(self,url): return '<h1>Something changed</h1>'
        with tempfile.TemporaryDirectory() as d:
            db=Store(Path(d)/'db.sqlite3')
            ad=Listing('oglasi','1','https://test/ad','Stan','prodaja','stan',location_raw='Petrovaradin').validate(); db.save(ad)
            config={'sources':[{'id':'oglasi','searches':[{'url':'https://test/list','transaction':'prodaja','property_type':'stan'}]}]}
            result=collect(db,config,client=Fake())
            self.assertEqual(result[0]['status'],'partial')
            self.assertEqual(db.listings()[0]['status'],'observed');db.close()

    def test_duplicates_do_not_cross_transaction_or_kind(self):
        a=Listing('a','1','https://a/ad','Stan','prodaja','stan',location='Petrovaradin',price=100,area_m2=30,currency='EUR',price_basis='total',description='Identican opis nekretnine '*20).to_dict()
        b=dict(a,source='b',url='https://b/ad')
        self.assertEqual(len(candidates([a,b])),1)
        self.assertFalse(candidates([a,dict(b,transaction='izdavanje')]))
        self.assertFalse(candidates([a,dict(b,property_type='kuca')]))

    def test_export_escapes_html_and_csv_formulas(self):
        a=Listing('a','1','https://a/ad','<script>alert(1)</script>','prodaja','stan',description='=malicious').to_dict()
        a.update(first_seen='',last_seen='',status='observed')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'report.html'; report(path,[a]); markup=path.read_text(encoding='utf-8')
            self.assertIn('&lt;script&gt;alert(1)',markup)
            a['title']='=SUM(1,2)'; path=Path(d)/'out.csv'; export(path,[a],'csv')
            self.assertIn("'=SUM(1,2)",path.read_text(encoding='utf-8-sig'))

if __name__=='__main__': unittest.main()
