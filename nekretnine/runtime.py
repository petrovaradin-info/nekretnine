"""Keep application temporary files and caches beside the project."""
import os
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def configure_paths():
    temporary=ROOT/'.runtime'/'tmp'
    cache=ROOT/'.cache'/'pip'
    temporary.mkdir(parents=True,exist_ok=True)
    cache.mkdir(parents=True,exist_ok=True)
    for key in ('TEMP','TMP','TMPDIR'):os.environ[key]=str(temporary)
    os.environ['PIP_CACHE_DIR']=str(cache)
    tempfile.tempdir=str(temporary)


def retain_backups(directory, keep=14):
    directory=Path(directory).resolve()
    candidates=[path for path in directory.glob('nekretnine-*.sqlite3') if path.is_file() and not path.is_symlink() and path.resolve().parent==directory]
    candidates.sort(key=lambda path:(path.stat().st_mtime_ns,path.name),reverse=True)
    for path in candidates[keep:]:path.unlink()
