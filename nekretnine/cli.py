import argparse
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from .collector import collect
from .store import Store
from .model import TRANSACTIONS, PROPERTY_TYPES
from .export import export, report, candidates, write_json

ROOT=Path(__file__).resolve().parents[1]

def positive(value):
    n=int(value)
    if n <= 0: raise argparse.ArgumentTypeError('Must be positive')
    return n

def main(argv=None):
    parser=argparse.ArgumentParser(description='Sakupljac nekretnina za Petrovaradin')
    parser.add_argument('--database',type=Path,default=ROOT/'data/nekretnine.sqlite3')
    parser.add_argument('--config',type=Path,default=ROOT/'sources.json')
    subs=parser.add_subparsers(dest='command',required=True)
    p=subs.add_parser('collect')
    p.add_argument('--source'); p.add_argument('--refresh',action='store_true')
    p.add_argument('--max-details',type=positive); p.add_argument('--max-pages',type=positive)
    p.add_argument('--log-file',type=Path)
    p.add_argument('--progress-interval',type=positive,default=10)
    p.add_argument('--transaction',choices=TRANSACTIONS); p.add_argument('--type',dest='property_type',choices=PROPERTY_TYPES)
    p=subs.add_parser('status')
    p.add_argument('--live',action='store_true')
    p=subs.add_parser('watch',help='Prikaz procenta i procene vremena u drugom terminalu')
    p.add_argument('--interval',type=positive,default=5)
    p.add_argument('--once',action='store_true')
    for name in ('export','report','candidates'):
        p=subs.add_parser(name)
        p.add_argument('--transaction',choices=TRANSACTIONS); p.add_argument('--type',dest='property_type',choices=PROPERTY_TYPES)
        p.add_argument('--output',type=Path)
        if name=='export': p.add_argument('--format',choices=('json','csv'),default='json')
    args=parser.parse_args(argv)
    progress_path=args.database.with_suffix('.progress.json')
    if args.command=='watch' or args.command=='status' and args.live:
        from .progress import watch
        try:return watch(progress_path,getattr(args,'interval',5),getattr(args,'once',True))
        except KeyboardInterrupt:return 0
    store=Store(args.database)
    try:
        if args.command=='collect':
            config=json.loads(args.config.read_text(encoding='utf-8'))
            ids={s['id'] for s in config['sources']}
            if args.source and args.source not in ids: parser.error('Unknown source; supported: '+', '.join(sorted(ids)))
            log=args.log_file or ROOT/'logs'/f'collect-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.log'
            log.parent.mkdir(parents=True,exist_ok=True)
            logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[logging.StreamHandler(),logging.FileHandler(log,encoding='utf-8')],force=True)
            print('Log:',log)
            from .locking import CollectionLock,CollectionBusy
            try:
                with CollectionLock(args.database.with_suffix('.collect.lock')):
                    reports=collect(store,config,args.source,args.transaction,args.property_type,args.max_details,args.max_pages,args.refresh,progress_path=progress_path,progress_interval=args.progress_interval,log_file=log)
            except CollectionBusy as e:
                print(e);return 3
            print(json.dumps(reports,ensure_ascii=False,indent=2))
            if any(r['status']=='interrupted' for r in reports): return 130
            return 0 if reports and all(r['status']=='ok' for r in reports) else 2
        if args.command=='status':
            print(json.dumps(store.status(),ensure_ascii=False,indent=2)); return 0
        rows=store.listings(args.transaction,args.property_type)
        if args.command=='export':
            path=args.output or ROOT/'data'/('nekretnine.'+args.format)
            export(path,rows,args.format)
        elif args.command=='report':
            path=args.output or ROOT/'data/nekretnine-pregled.html'; report(path,rows)
        else:
            path=args.output or ROOT/'data/nekretnine-duplikati.json'; write_json(path,candidates(rows))
        print(path); return 0
    except KeyboardInterrupt:
        logging.warning("Prikupljanje prekinuto; sacuvani podaci ostaju u bazi")
        return 130
    finally: store.close()
