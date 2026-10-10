"""Live weighted progress per search, not merely per website."""
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread

LOG=logging.getLogger(__name__)


def duration(seconds):
    if seconds is None: return 'racunam...'
    seconds=max(0,round(seconds))
    if seconds<60:return f'{seconds}s'
    minutes=math.ceil(seconds/60)
    return f'{minutes//60}h {minutes%60:02d}m' if minutes>=60 else f'{minutes}m'


def format_progress(state):
    return (f"{state['label']} ~{state['percent']}% | pretrage {state['finished']}/{state['total']}"
            f" | proteklo {duration(state['elapsed'])} | preostalo ~{duration(state['eta'])}"
            f" | oglasi {state['processed']}/{state['expected_ads']} (procena)"
            f" | sacuvano {state['saved']} | kes {state['cached']} | greske {state['errors']}"
            f" | pretrage sa problemom {state['issues']} | aktivno: {state['active'] or '-'}")


class Progress:
    def __init__(self,store,targets,path=None,interval=10,log_file=None,clock=time.monotonic):
        self.clock=clock;self.started=clock();self.path=Path(path) if path else None
        self.interval=interval;self.log_file=str(log_file) if log_file else None
        self.database=str(store.path.resolve());self.guard=Lock();self.emit_guard=Lock()
        self.stop=Event();self.phase='collecting';self.states={}
        for source,search in targets:
            key=(source['id'],search['url'])
            rows=store.db.execute('SELECT details FROM runs WHERE source=? AND search_url=? ORDER BY id DESC LIMIT 20',key).fetchall()
            history={}
            for row in rows:
                try:value=json.loads(row[0])
                except (ValueError,TypeError):continue
                if not value.get('limited') and not value.get('errors') and value.get('pages',0)>0:
                    history=value;break
            ads=max(1,history.get('discovered',0)) if history else 50
            pages=max(1,history.get('pages',0))
            self.states[key]=dict(expected_ads=ads,expected_pages=pages,processed=0,pages=0,saved=0,cached=0,errors=0,status=None,active=False,label=f"{source['id']} / {search['transaction']} / {search['property_type']} / {search.get('location',search['url'].rsplit('/',1)[-1])}",url=search['url'])
        self.thread=Thread(target=self.run,name='collector-progress',daemon=True)

    def update(self,key,counts=None,pending_pages=0,pending_ads=0,total_ads=None,page_size=None,status=None):
        with self.guard:
            s=self.states[key];s['active']=status is None;s['status']=status
            if counts:
                for name in ('pages','processed','saved','cached'):s[name]=counts.get(name,0)
                s['errors']=len(counts.get('errors',[]))
                s['expected_ads']=max(s['expected_ads'],counts.get('discovered',0)+pending_ads,s['processed'])
            if total_ads is not None:
                s['expected_ads']=max(s['expected_ads'],total_ads)
                if page_size:s['expected_pages']=max(s['expected_pages'],math.ceil(total_ads/page_size))
            s['expected_pages']=max(s['expected_pages'],s['pages']+pending_pages)
            if status is not None:s['active']=False

    def snapshot(self):
        with self.guard:
            states=list(self.states.values());total_work=sum(s['expected_ads']+s['expected_pages'] for s in states)
            done=sum(s['expected_ads']+s['expected_pages'] if s['status'] is not None and s['status']!='interrupted' else min(s['processed']+s['pages'],(s['expected_ads']+s['expected_pages'])*.99) for s in states)
            elapsed=max(0,self.clock()-self.started);ratio=done/total_work if total_work else 0
            finished=sum(s['status'] is not None for s in states)
            ended=self.phase=='complete' and finished==len(states)
            eta=0 if ended else elapsed*(1-ratio)/ratio if self.phase=='collecting' and elapsed>=30 and ratio>0 else None
            active=next((s for s in states if s['active']),{})
            return dict(version=1,pid=os.getpid(),database=self.database,log_file=self.log_file,updated_at=datetime.now(timezone.utc).isoformat(),phase=self.phase,
                        label='KRAJ POKUSAJA' if ended else 'PREKINUTO' if self.phase=='interrupted' else 'GRESKA' if self.phase=='error' else 'NAPREDAK',
                        percent=100 if ended else min(99,round(ratio*100)),elapsed=elapsed,eta=eta,finished=finished,total=len(states),active=active.get('label'),active_url=active.get('url'),
                        processed=sum(s['processed'] for s in states),expected_ads=sum(s['expected_ads'] for s in states),pages=sum(s['pages'] for s in states),saved=sum(s['saved'] for s in states),cached=sum(s['cached'] for s in states),errors=sum(s['errors'] for s in states),issues=sum(s['status'] not in (None,'ok') for s in states),
                        searches=[dict(s,source=k[0]) for k,s in self.states.items()])

    def emit(self):
        with self.emit_guard:
            state=self.snapshot();LOG.info(format_progress(state))
            if self.path:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temp=self.path.with_name(self.path.name+f'.{os.getpid()}.tmp')
                try:
                    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
                    temp.replace(self.path)
                except OSError as e:LOG.warning('Ne mogu da upisem prikaz napretka: %s',e)

    def run(self):
        while not self.stop.wait(self.interval):self.emit()

    def start(self):self.emit();self.thread.start()

    def finish(self,phase='complete'):
        self.stop.set();self.thread.join()
        with self.guard:self.phase=phase
        self.emit()


def process_alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        dll=ctypes.WinDLL('kernel32',use_last_error=True)
        dll.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];dll.OpenProcess.restype=wintypes.HANDLE
        dll.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        dll.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=dll.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        code=wintypes.DWORD()
        try:return bool(dll.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:dll.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def watch(path,interval=5,once=False):
    previous=None
    while True:
        try:state=json.loads(Path(path).read_text(encoding='utf-8'))
        except FileNotFoundError:
            print('Nema prikaza napretka. Pokrenite novu verziju sakupljaca; stari proces ima samo log.');return 2
        except (OSError,ValueError) as e:
            print('Ne mogu da procitam napredak:',e);return 2
        if state['phase']=='collecting' and not process_alive(state['pid']):
            print('Proces vise nije aktivan. Poslednji sacuvani prikaz:');print(format_progress(state));return 2
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['updated_at'])).total_seconds()
        if state['updated_at']!=previous:
            print(format_progress(state),flush=True)
            if state.get('log_file'):print('Log:',state['log_file'],flush=True)
            previous=state['updated_at']
        if age>60 and state['phase']=='collecting':print(f'Prikaz nije osvezen {round(age)}s; proverite log.',flush=True)
        if once:return 0
        if state['phase']!='collecting':return 0 if state['phase']=='complete' and not state['issues'] else 2
        time.sleep(interval)
