"""Refresh existing listings and retire old ones only after a successful check."""
import logging
from .collector import Client, FetchError
from .parsers import detail
from .model import LOCATIONS, now
LOG=logging.getLogger(__name__)

def update(store, config, client=None, interval_hours=None, progress_path=None, log_file=None):
    client=client or Client(config.get('request_delay',2))
    source_ids={s['id'] for s in config['sources'] if s.get('enabled',True)}
    rows=[r for r in store.due(interval_hours) if r['source'] in source_ids]
    result=dict(total=len(rows),checked=0,saved=0,unavailable=0,expired=0,errors=[])
    from .progress import Progress
    target=({'id':'update'},{'url':'update','transaction':'provera','property_type':'cena i dostupnost','location':'sve lokacije'})
    progress=Progress(store,[target] if rows else [],path=progress_path,log_file=log_file)
    key=('update','update')
    if rows:
        progress.states[key]['expected_ads']=len(rows)
        progress.states[key]['expected_pages']=0
    progress.start();phase='error'
    successful=set()
    try:
        for row in rows:
            if row['source'] not in source_ids:continue
            try:
                ad=detail(client.get(row['url']),row['url'],row['source'],{'transaction':row['transaction_type'],'property_type':row['property_type']})
                if ad.location not in LOCATIONS or 'title_location_conflict' in ad.review_reasons:
                    raise ValueError('Location needs review; existing record retained')
                import json
                previous=json.loads(row['payload'])
                if previous.get('price') is not None and ad.price is None:raise ValueError('Missing price; existing record retained')
                if 'search_category_conflict' in ad.review_reasons:raise ValueError('Category conflict; existing record retained')
                store.save(ad);successful.add(ad.url);result['saved']+=1
                LOG.info('UPDATED committed %s price=%s',row['url'],ad.price)
            except FetchError as error:
                if error.status in (404,410):
                    store.unavailable(row['url']);result['unavailable']+=1
                    LOG.info('UNAVAILABLE probable sold/withdrawn %s',row['url'])
                else:result['errors'].append({'url':row['url'],'error':str(error)})
            except ValueError as error:result['errors'].append({'url':row['url'],'error':str(error)})
            result['checked']+=1
            progress.update(key,dict(processed=result['checked'],saved=result['saved'],errors=result['errors'],discovered=result['total']))
            LOG.info('UPDATE %s/%s (~%s%%) saved=%s unavailable=%s errors=%s',result['checked'],result['total'],round(result['checked']*100/max(1,result['total'])),result['saved'],result['unavailable'],len(result['errors']))
        result['expired']=store.expire(eligible_urls=successful)
        store.record('maintenance','update',now(),'partial' if result['errors'] else 'ok',result)
        if rows:progress.update(key,dict(processed=result['checked'],saved=result['saved'],errors=result['errors']),status='partial' if result['errors'] else 'ok')
        phase='complete'
        return result
    except KeyboardInterrupt:
        phase='interrupted';raise
    finally:
        progress.finish(phase)
        if hasattr(client,'session'):client.session.close()
