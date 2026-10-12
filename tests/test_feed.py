import json
import tempfile
import unittest
from pathlib import Path
from nekretnine.feed import export_feed,record,COLUMNS
class FeedTests(unittest.TestCase):
    def test_missing_contacts_and_publication_remain_empty(self):
        row=record({'url':'https://test/ad','source':'test','source_id':'1','first_seen':'today','updated_at':'today','property_type':'plac','plot_area_m2':1000,'area_m2':30})
        self.assertEqual(row['datum_objave'],'');self.assertEqual(row['kontakt_email'],'');self.assertEqual(row['kontakt_tel'],'')
        self.assertEqual(row['povrsina'],1000);self.assertEqual(row['id'],'test:1')
    def test_json_columns(self):
        ad={'url':'https://test/ad','source':'test','title':'Stan','price':123,'currency':'EUR','price_basis':'monthly','photos':[{'url':'https://test/main.jpg'}]}
        with tempfile.TemporaryDirectory() as directory:
            paths=export_feed(Path(directory)/'feed.json',[ad])
            row=json.loads(paths[0].read_text(encoding='utf-8'))[0]
            self.assertEqual(list(row),COLUMNS);self.assertEqual(row['cena'],123)
            self.assertEqual(row['slika_url'],'https://test/main.jpg')
    def test_limit_and_obsolete_parts(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'feed.json'
            rows=[{'url':f'https://test/{i:05d}','source':'test','source_id':str(i)} for i in range(10000)]
            path.write_text('old');path.with_suffix('.csv').write_text('old csv')
            unrelated=path.parent/'other-001.json';unrelated.write_text('keep')
            outputs=export_feed(path,rows)
            chunks=[json.loads(part.read_text(encoding='utf-8')) for part in outputs]
            self.assertEqual([len(chunk) for chunk in chunks],[4999,4999,2])
            self.assertEqual(len({ad['link'] for chunk in chunks for ad in chunk}),10000)
            self.assertFalse(path.exists());self.assertFalse(path.with_suffix('.csv').exists())
            outputs=export_feed(path,rows[:4999])
            self.assertEqual(len(outputs),1);self.assertFalse((path.parent/'feed-002.json').exists())
            self.assertTrue(unrelated.exists())
    def test_empty_export_and_csv_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'feed.json'
            self.assertEqual(json.loads(export_feed(path,[])[0].read_text()),[])
            with self.assertRaises(ValueError):export_feed(path,[],'csv')

    def test_title_limit_and_image_url_encoding(self):
        from nekretnine.feed import export_url
        row=record({'url':'https://test/ad','source':'test','title':'Dugačak naslov '*30,'photos':[{'url':'https://media.oglasi.rs/id/large-prodaja kuća (2).jpg'}]})
        self.assertLessEqual(len(row['naslov']),200)
        self.assertEqual(row['slika_url'],'https://media.oglasi.rs/id/large-prodaja%20ku%C4%87a%20%282%29.jpg')
        self.assertEqual(export_url(row['slika_url']),row['slika_url'])
        self.assertEqual(export_url('https://test/path?q=č ć&n=2'),'https://test/path?q=%C4%8D%20%C4%87&n=2')
        self.assertEqual(export_url('not a URL'),'')
        self.assertEqual(export_url('https://test/%wrong.jpg'),'https://test/%25wrong.jpg')
