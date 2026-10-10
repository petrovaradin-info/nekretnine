import json
import random
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from PIL import Image
from nekretnine.model import Listing, local_location, price_basis
from nekretnine.grouping import compare, groups
from nekretnine.photos import fingerprint, photo_matches
from nekretnine.store import Store
from nekretnine.collector import collect
from nekretnine.export import export, report


def row(url='https://a/ad', **changes):
    result=Listing('a','1',url,'Stan','izdavanje','stan',description='Jedinstven opis prostranog stana sa posebnom organizacijom soba. '*6,location_raw='Petrovaradin',price=500,currency='EUR',area_m2=50,rooms='Dvosoban',floor='1. sprat').validate().to_dict()
    result.update(changes)
    return result


def photos():
    return [{'sha256':'a','dhash':'aaaaaaaaaaaaaaaa','ahash':'a5a5a5a5a5a5a5a5'}, {'sha256':'b','dhash':'cccccccccccccccc','ahash':'cccc3333cccc3333'}]


class GroupingTests(unittest.TestCase):
    def test_area_and_price_alone_never_merge(self):
        a=row(description='Stan u novogradnji')
        b=row('https://b/ad',source='b',description='Drugi stan u istoj zgradi')
        self.assertIsNone(compare(a,b)); self.assertEqual(len(groups([a,b])),2)

    def test_two_photos_and_layout_group_all_originals(self):
        a=row(description='Prva agencija',photos=photos())
        b=row('https://b/ad',source='b',description='Drugi opis',photos=photos(),price=520,rooms='2',floor='1/3 sprata')
        evidence=compare(a,b);self.assertTrue(evidence['automatic'])
        result=groups([a,b]);self.assertEqual(len(result),1)
        self.assertEqual(result[0]['listing_count'],2)
        self.assertEqual(result[0]['price_min'],500);self.assertEqual(result[0]['price_max'],520)
        self.assertEqual({x['url'] for x in result[0]['listings']},{a['url'],b['url']})
        self.assertEqual(groups([b,a])[0]['group_id'],result[0]['group_id'])

    def test_conflicting_units_in_new_build_do_not_merge(self):
        a=row(photos=photos(),agency_id='123',advertiser='Agencija')
        for change in ({'floor':'2/4'},{'rooms':'3'},{'agency_id':'456'},{'location':'Sremska Kamenica'},{'transaction':'prodaja'},{'property_type':'kuca'},{'price_basis':'daily'}):
            b=row('https://b/ad',source='b',photos=photos(),agency_id='123',advertiser='Agencija')|change
            self.assertIsNone(compare(a,b),change)

    def test_single_photo_is_only_candidate_without_other_identity(self):
        a=row(description='Prvi opis',photos=photos()[:1])
        b=row('https://b/ad',description='Drugi opis',photos=photos()[:1])
        self.assertFalse(compare(a,b)['automatic']);self.assertEqual(len(groups([a,b])),2)

    def test_duplicate_gallery_photo_cannot_count_twice(self):
        self.assertEqual(photo_matches(photos()[:1]*3,photos()[:1]*4),1)

    def test_same_code_requires_same_advertiser(self):
        a=row(description='Prvi',agency_id='123',advertiser='Prva agencija')
        b=row('https://b/ad',description='Drugi',agency_id='123',advertiser='Druga agencija')
        self.assertIsNone(compare(a,b))
        b['advertiser']='Prva agencija';self.assertTrue(compare(a,b)['automatic'])

    def test_complete_link_prevents_chaining(self):
        a=row('https://a/ad',photos=photos(),description='a',floor='1')
        b=row('https://b/ad',photos=photos(),description='b',floor='')
        c=row('https://c/ad',photos=photos(),description='c',floor='2')
        # Agency evidence allows A-B and B-C but A-C has a floor conflict.
        for r in (a,b,c):r.update(agency_id='123',advertiser='Same agency')
        self.assertTrue(compare(a,b)['automatic']);self.assertTrue(compare(b,c)['automatic'])
        self.assertEqual(sorted(g['listing_count'] for g in groups([a,b,c])),[1,2])

    def test_grouped_export_and_report_keep_both_source_links(self):
        a=row(photos=photos()); b=row('https://b/ad',source='b',photos=photos())
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.json';export(p,[a,b],'json');self.assertEqual(json.loads(p.read_text())[0]['listing_count'],2)
            export(p,[a,b],'json',flat=True);self.assertEqual(len(json.loads(p.read_text())),2)
            p=Path(d)/'out.html';report(p,[a,b]);markup=p.read_text(encoding='utf-8')
            self.assertEqual(markup.count('<article '),1)
            self.assertIn('https://a/ad',markup);self.assertIn('https://b/ad',markup)
            p=Path(d)/'out.csv';export(p,[a,b],'csv');self.assertIn('group_id;group_size',p.read_text(encoding='utf-8-sig'))


class ScopeAndPricingTests(unittest.TestCase):
    def test_only_three_explicit_locations(self):
        for raw,expected in [('Petrovaradin (Novi Sad)','Petrovaradin'),('Novi Sad, Sremska Kamenica, Popovica','Sremska Kamenica'),('Сремски Карловци','Sremski Karlovci'),('Novi Sad',''),('Beograd',''),('Petrovaradin / Sremska Kamenica','')]:
            self.assertEqual(local_location(raw),expected)

    def test_conflicting_title_and_source_location_are_quarantined(self):
        ad=Listing('a','1','https://a/ad','Stan u Sremskoj Kamenici','prodaja','stan',location_raw='Sremski Karlovci').validate()
        self.assertIn('title_location_conflict',ad.review_reasons)
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'db');store.save(ad)
            self.assertFalse(store.listings())
            self.assertEqual(len(store.listings(include_outside=True)),1);store.close()

    def test_prices_have_transaction_defaults_and_explicit_exceptions(self):
        self.assertEqual(price_basis('izdavanje')[0],'monthly')
        self.assertEqual(price_basis('izdavanje',description='Stan se sastoji od dnevnog boravka i dve sobe.')[0],'monthly')
        self.assertEqual(price_basis('prodaja',description='Odlično za stan na dan')[0],'total')
        self.assertEqual(price_basis('izdavanje','Stan na dan')[0],'daily')
        self.assertEqual(price_basis('izdavanje',description='180 EUR po osobi')[0],'per_person')
        self.assertEqual(price_basis('izdavanje',description='Ne izdaje se stan na dan.')[0],'monthly')

    def test_old_rows_reclassified_without_faking_fetch_dates(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'db')
            ad=Listing('a','1','https://a/ad','Stan','izdavanje','stan',location_raw='Sremska Kamenica')
            store.save(ad)
            old=store.db.execute('SELECT fetched_at FROM listings').fetchone()[0]
            result=store.listings()[0]
            self.assertEqual(result['location'],'Sremska Kamenica');self.assertEqual(result['price_basis'],'monthly');self.assertEqual(result['fetched_at'],old)
            store.save(Listing('a','2','https://a/2','Stan','prodaja','stan',location_raw='Novi Sad'))
            self.assertEqual(len(store.listings()),1);self.assertEqual(len(store.listings(include_outside=True)),2)
            store.close()

    def test_collector_excludes_outside_and_unconfirmed(self):
        class Fake:
            def get(self,url):
                if url.endswith('/list'):return '<a href="/oglas/03-1/ad">Stan</a>'
                return '<h1>Stan</h1><script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[{"name":"Prodaja stanova"}]}</script><table><tr><td>Lokacija:</td><td>Beograd</td></tr></table><div itemprop="description">Petrovaradin u opisu nije lokacija</div>'
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'db')
            config={'photo_hash_limit':0,'sources':[{'id':'oglasi','searches':[{'url':'https://a/list','transaction':'prodaja','property_type':'stan'}]}]}
            results=collect(store,config,client=Fake())
            self.assertEqual(results[0]['outside_area'],1);self.assertFalse(store.listings());store.close()


class PhotoTests(unittest.TestCase):
    def test_visual_hash_survives_resize_and_compression(self):
        rng=random.Random(7)
        image=Image.new('RGB',(320,240)); pixels=[]
        for y in range(240):
            for x in range(320):
                pixels.append(((x//35*37+y//30*53)%256,(x*2+y)%256,rng.randrange(100)))
        image.putdata(pixels)
        original=BytesIO();image.save(original,format='PNG')
        variant=BytesIO();image.resize((160,120)).save(variant,format='JPEG',quality=85)
        a,b=fingerprint(original.getvalue()),fingerprint(variant.getvalue())
        self.assertTrue(a);self.assertTrue(b);self.assertNotEqual(a['sha256'],b['sha256'])
        self.assertEqual(photo_matches([a],[b]),1)

    def test_blank_and_small_images_are_not_identity_evidence(self):
        for size in [(320,240),(40,40)]:
            image=Image.new('RGB',size,'white');buf=BytesIO();image.save(buf,format='PNG')
            self.assertIsNone(fingerprint(buf.getvalue()))

if __name__=='__main__':unittest.main()
