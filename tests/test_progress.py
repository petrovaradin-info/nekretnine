import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nekretnine.store import Store
from nekretnine.progress import Progress, watch, process_alive
from nekretnine.locking import CollectionLock, CollectionBusy
from nekretnine.parsers import listing_total

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Store(self.root/'test.sqlite3')
        self.addCleanup(self.store.close)
        self.time=0
        self.targets=[({'id':'source'}, {'url':f'https://site/{i}','transaction':'prodaja','property_type':'stan'}) for i in range(2)]
    def progress(self):
        return Progress(self.store,self.targets,self.root/'progress.json',clock=lambda:self.time)
    def test_independent_searches_and_eta(self):
        p=self.progress();self.time=60
        p.update(('source','https://site/0'),status='ok')
        state=p.snapshot()
        self.assertEqual(state['percent'],50)
        self.assertEqual(state['eta'],60)
        self.assertEqual(state['finished'],1)
    def test_discovery_revises_estimate(self):
        p=self.progress();key=('source','https://site/0')
        p.update(key,{'processed':25,'pages':1})
        before=p.snapshot()['percent']
        p.update(key,total_ads=500,page_size=20)
        self.assertLess(p.snapshot()['percent'],before)
    def test_complete_reports_issues(self):
        p=self.progress();p.start()
        p.update(('source','https://site/0'),status='partial')
        p.update(('source','https://site/1'),status='ok')
        self.assertLess(p.snapshot()['percent'],100)
        p.finish()
        state=json.loads((self.root/'progress.json').read_text())
        self.assertEqual(state['percent'],100)
        self.assertEqual(state['issues'],1)
        self.assertEqual(state['phase'],'complete')
        self.assertTrue(process_alive(state['pid']))
        self.assertFalse(list(self.root.glob('*.tmp')))
    def test_interruption_never_claims_completion(self):
        p=self.progress();p.start();self.time=90
        p.update(('source','https://site/0'),{'processed':10},status='interrupted')
        p.finish('interrupted')
        self.assertLess(p.snapshot()['percent'],100)
        self.assertIsNone(p.snapshot()['eta'])
    def test_history_excludes_limited_and_failed_runs(self):
        self.store.record('source','https://site/0','now','ok',dict(pages=4,discovered=100,limited=False))
        self.store.record('source','https://site/0','now','partial',dict(pages=1,discovered=1,limited=True))
        self.store.record('source','https://site/0','now','partial',dict(pages=1,discovered=2,errors=['failed']))
        p=self.progress()
        self.assertEqual(p.states[('source','https://site/0')]['expected_ads'],100)
        self.assertEqual(p.states[('source','https://site/1')]['expected_ads'],50)
    def test_watch_missing_and_dead_process(self):
        with patch('builtins.print'):
            self.assertEqual(watch(self.root/'missing',once=True),2)
            p=self.progress();p.emit()
            with patch('nekretnine.progress.process_alive',return_value=False):
                self.assertEqual(watch(self.root/'progress.json',once=True),2)
    def test_lock_prevents_overlap_and_releases_on_exception(self):
        path=self.root/'collect.lock'
        with self.assertRaisesRegex(ValueError,'test'):
            with CollectionLock(path):
                with self.assertRaises(CollectionBusy):
                    with CollectionLock(path):pass
                raise ValueError('test')
        with CollectionLock(path):pass
    def test_published_total_and_missing_total(self):
        self.assertEqual(listing_total('<h1>Stanovi</h1><span>1.234 oglasa</span>'),1234)
        self.assertEqual(listing_total('<h1>Stanovi</h1><span>0 oglasa</span>'),0)
        self.assertIsNone(listing_total('<h1>Stanovi</h1><div>123 m2</div>'))

if __name__=='__main__':unittest.main()
