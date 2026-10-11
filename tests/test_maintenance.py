import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import Mock,patch
from nekretnine.store import Store
from nekretnine.model import Listing
from nekretnine.collector import collect,FetchError
from nekretnine.maintenance import update

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db.sqlite3'
        self.store=Store(self.path);self.addCleanup(self.store.close)
        self.ad=Listing('test','1','https://test/ad','Stan','prodaja','stan',location_raw='Petrovaradin',price=100000,currency='EUR').validate()
        self.config={'photo_hash_limit':6,'sources':[{'id':'test','searches':[{'url':'https://test/list','transaction':'prodaja','property_type':'stan'}]}]}
    def old(self):
        self.store.save(self.ad)
        with self.store.db:self.store.db.execute("UPDATE listings SET first_seen='2025-01-01T00:00:00+00:00',checked_at=NULL")
    def test_commit_is_visible_before_close_and_backup_restores(self):
        self.store.save(self.ad)
        with sqlite3.connect(self.path) as observer:self.assertEqual(observer.execute('SELECT COUNT(*) FROM listings').fetchone()[0],1)
        path=self.path.with_name('backup.db');self.store.backup(path)
        with sqlite3.connect(path) as restored:self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_known_urls_never_fetch_details_or_images(self):
        self.old();client=Mock();client.get.return_value='html'
        with patch('nekretnine.collector.listing_page',return_value=([self.ad.url],[],False)):
            result=collect(self.store,self.config,client=client)
        client.get.assert_called_once_with('https://test/list');client.get_image.assert_not_called()
        self.assertEqual(result[0]['cached'],1)
    def test_new_listing_commits_without_photo_requests(self):
        client=Mock();client.get.return_value='html'
        with patch('nekretnine.collector.listing_page',return_value=([self.ad.url],[],False)),patch('nekretnine.collector.detail',return_value=self.ad):
            result=collect(self.store,self.config,client=client)
        self.assertEqual(result[0]['saved'],1);client.get_image.assert_not_called()
    def test_same_price_expires_and_leaves_tombstone_and_history(self):
        self.old();client=Mock()
        with patch('nekretnine.maintenance.detail',return_value=self.ad):result=update(self.store,self.config,client=client)
        self.assertEqual(result['expired'],1);self.assertEqual(self.store.listings(),[])
        self.assertTrue(self.store.known(self.ad.url))
        self.assertGreater(self.store.db.execute('SELECT COUNT(*) FROM versions').fetchone()[0],0)
    def test_price_change_resets_six_month_window(self):
        self.old();self.ad.price=95000
        with patch('nekretnine.maintenance.detail',return_value=self.ad):result=update(self.store,self.config,client=Mock())
        self.assertEqual(result['expired'],0);self.assertEqual(self.store.listings()[0]['price'],95000)
        self.assertTrue(self.store.db.execute('SELECT price_changed_at FROM listings').fetchone()[0])
    def test_404_marks_unavailable_but_network_error_retains(self):
        self.old();client=Mock();client.get.side_effect=FetchError('timeout')
        result=update(self.store,self.config,client=client)
        self.assertEqual(len(result['errors']),1);self.assertEqual(len(self.store.listings(active_only=True)),1)
        client.get.side_effect=FetchError('gone',404);result=update(self.store,self.config,client=client)
        self.assertEqual(result['unavailable'],1);self.assertEqual(self.store.listings(active_only=True),[])
        self.assertEqual(len(self.store.listings()),1)
    def test_missing_price_does_not_erase_or_expire_existing(self):
        self.old();self.ad.price=None
        with patch('nekretnine.maintenance.detail',return_value=self.ad):result=update(self.store,self.config,client=Mock())
        self.assertEqual(len(result['errors']),1);self.assertEqual(result['expired'],0)
        self.assertEqual(self.store.listings()[0]['price'],100000)
    def test_interruption_preserves_already_committed_updates(self):
        self.old();self.ad.price=90000
        second=Listing('test','2','https://test/second','Stan','prodaja','stan',location_raw='Petrovaradin').validate();self.store.save(second)
        with self.store.db:self.store.db.execute('UPDATE listings SET checked_at=NULL')
        client=Mock();client.get.side_effect=['html',KeyboardInterrupt()]
        with patch('nekretnine.maintenance.detail',return_value=self.ad):
            with self.assertRaises(KeyboardInterrupt):update(self.store,self.config,client=client)
        self.assertEqual(json.loads(self.store.db.execute('SELECT payload FROM listings WHERE url=?',(self.ad.url,)).fetchone()[0])['price'],90000)

    def test_daily_due_uses_local_day_not_24_hour_rolling_window(self):
        self.store.save(self.ad)
        self.assertEqual(self.store.due(),[])
        with self.store.db:self.store.db.execute("UPDATE listings SET checked_at='2025-01-01T23:00:00+00:00'")
        self.assertEqual(len(self.store.due()),1)
    def test_interrupted_json_write_preserves_previous_export(self):
        from nekretnine.export import write_json
        path=self.path.with_name('export.json');path.write_text('old',encoding='utf-8')
        with patch.object(Path,'replace',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):write_json(path,{'new':'value'})
        self.assertEqual(path.read_text(),'old')
        self.assertFalse(list(path.parent.glob('*.tmp')))

if __name__=='__main__':unittest.main()
