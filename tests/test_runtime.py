import os
import tempfile
import unittest
from pathlib import Path
from nekretnine.runtime import ROOT,configure_paths,retain_backups

class RuntimeTests(unittest.TestCase):
    def test_temporary_files_and_cache_stay_in_project(self):
        configure_paths()
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT/'.runtime'/'tmp'))
        self.assertEqual(Path(os.environ['PIP_CACHE_DIR']),ROOT/'.cache'/'pip')
    def test_backup_retention_preserves_manual_backup_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            for i in range(18):(path/f'nekretnine-{i:02}.sqlite3').write_text('backup')
            (path/'before-fix004.sqlite3').write_text('manual')
            (path/'unrelated.txt').write_text('keep')
            retain_backups(path)
            self.assertEqual(len(list(path.glob('nekretnine-*.sqlite3'))),14)
            self.assertTrue((path/'before-fix004.sqlite3').exists())
            self.assertTrue((path/'unrelated.txt').exists())
