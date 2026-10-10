from collections import deque
import logging
import time
from urllib.parse import urlsplit, urljoin
import requests
from protego import Protego
from .model import now, canonical
from .parsers import listing_page, detail, listing_total
from .model import now, canonical, LOCATIONS, local_location
from .parsers import listing_page, detail

LOG = logging.getLogger(__name__)
AGENT = "PetrovaradinRealEstate/0.1"

class FetchError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status

class Client:
    def __init__(self, delay=2):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers['User-Agent'] = AGENT
        self.last = {}
        self.robots = {}

    def request(self, url, stream=False):
        host = urlsplit(url).netloc
        time.sleep(max(0, self.delay - (time.monotonic() - self.last.get(host, 0))))
        LOG.info('GET %s', url)
        try:
            r = self.session.get(url, timeout=(10, 30), allow_redirects=False, stream=stream)
            self.last[host] = time.monotonic()
            LOG.info('HTTP %s %s', r.status_code, url)
            if r.status_code >= 400:
                r.close()
                raise FetchError(f'HTTP {r.status_code}: {url}', r.status_code)
            r.encoding = 'utf-8' if 'charset=' not in r.headers.get('Content-Type','').lower() else r.encoding
            return r
        except requests.RequestException as e: raise FetchError(str(e)) from e

    def check_robots(self, url):
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            try:
                r = self.request(origin + '/robots.txt')
                if r.is_redirect: raise FetchError('robots.txt redirect requires manual verification')
                self.robots[origin] = Protego.parse(r.text)
            except FetchError as e:
                if e.status == 404: self.robots[origin] = Protego.parse('')
                else: raise
        robot = self.robots[origin]
        if not robot.can_fetch(url, AGENT): raise FetchError('robots.txt disallows ' + url)
        self.delay = max(self.delay, robot.crawl_delay(AGENT) or 0)

    def get_image(self, url):
        limit = 8 * 1024 * 1024
        for _ in range(5):
            self.check_robots(url)
            response = self.request(url, stream=True)
            with response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    if urlsplit(url).scheme not in ('https','http'): raise FetchError('Invalid image redirect')
                    continue
                if not response.headers.get('Content-Type','').lower().startswith('image/'):
                    raise FetchError('Unexpected photo content type')
                data=bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data)>limit: raise FetchError('Photo exceeds 8 MiB limit')
                return bytes(data)
        raise FetchError('Too many image redirects')

    def get(self, url):
        for _ in range(8):
            p = urlsplit(url)
            self.check_robots(url)
            r = self.request(url)
            if r.is_redirect:
                target = urljoin(url, r.headers['Location'])
                if urlsplit(target).netloc != p.netloc: raise FetchError('Unexpected cross-host redirect: ' + target)
                url = target
                continue
            if 'text/html' not in r.headers.get('Content-Type',''): raise FetchError('Unexpected response type')
            lower = r.text.lower()
            if '<title>just a moment' in lower or 'cf-chl-' in lower: raise FetchError('Access verification required')
            return r.text
        raise FetchError('Too many redirects')


def collect(store, config, only=None, transaction=None, property_type=None, max_details=None, max_pages=None, refresh=False, client=None, progress_path=None, progress_interval=10, log_file=None):
    from .progress import Progress
    targets=[(source,search) for source in config['sources'] for search in source.get('searches',[]) if (not only or source['id']==only) and (not transaction or search['transaction']==transaction) and (not property_type or search['property_type']==property_type)]
    progress=Progress(store,targets,path=progress_path,interval=progress_interval,log_file=log_file)
    progress.start()
    phase='error'
    try:
        result=_collect(store,config,only,transaction,property_type,max_details,max_pages,refresh,client,progress)
        phase='interrupted' if any(r['status']=='interrupted' for r in result) else 'complete'
        return result
    except KeyboardInterrupt:
        phase='interrupted';raise
    finally:progress.finish(phase)


def _collect(store, config, only=None, transaction=None, property_type=None, max_details=None, max_pages=None, refresh=False, client=None, progress=None):

    client = client or Client(config.get('request_delay', 2))
    reports = []
    try:
        for source in config['sources']:
            if only and source['id'] != only: continue
            for search in source.get('searches', []):
                if location and search.get('location') != location: continue
                if transaction and transaction != search['transaction']: continue
                if property_type and property_type != search['property_type']: continue
                key=(source['id'],search['url'])
                started = now();started_clock=time.monotonic()
                progress.update(key)
                counts = dict(pages=0, discovered=0, attempted=0, saved=0, cached=0, review=0, processed=0, errors=[])
                if not source.get('enabled', True) or not search.get('enabled', True):
                    counts['reason'] = search.get('note', source.get('note','pending adapter'))
                    store.record(source['id'], search['url'], started, 'pending_integration', counts)
                    progress.update(key,counts,status='pending_integration');progress.emit()
                    reports.append(dict(source=source['id'], url=search['url'], status='pending_integration', **counts))
                    continue
                queue, visited, seen = deque([search['url']]), set(), set()
                limited = False
                page_limit = max_pages or config.get('max_pages', 200)
                interrupted = False
                try:
                    while queue:
                        url = queue.popleft()
                        if url in visited: continue
                        if len(visited) >= page_limit:
                            limited = True; break
                        visited.add(url)
                        try:
                            html = client.get(url)
                            links, pages, empty = listing_page(html, url, source['id'])
                            counts['pages'] += 1
                            progress.update(key,counts,pending_pages=len(set(queue)-visited),pending_ads=len(set(links)-seen),total_ads=listing_total(html),page_size=len(links) or None)
                            if not links and not empty: raise ValueError('No listing links or confirmed empty result; parser/access needs review')
                            queue.extend(p for p in pages if p not in visited)
                            LOG.info('[%s %s %s] PAGE %s: %s listings', source['id'], search['transaction'], search['property_type'], counts['pages'], len(links))
                            for link in links:
                                if link in seen: continue
                                seen.add(link); counts['discovered'] += 1
                                if not refresh and store.fresh(link, config.get('refresh_hours',24)):
                                    store.seen(link); counts['cached'] += 1;counts['processed'] += 1
                                    progress.update(key,counts,pending_pages=len(set(queue)-visited))
                                    LOG.info('CACHED %s',link); continue
                                if max_details is not None and counts['attempted'] >= max_details:
                                    limited = True; break
                                counts['attempted'] += 1
                                try:
                                    ad = detail(client.get(link), link, source['id'], search)
                                    if ad.location not in LOCATIONS or 'title_location_conflict' in ad.review_reasons or (search.get('location') and ad.location != search['location']):
                                        counts['outside_area'] += 1; LOG.info('OUTSIDE AREA %s %s',ad.location_raw,link); continue
                                    if config.get('photo_hash_limit',6):
                                        from .photos import enrich_photos
                                        photo_errors = enrich_photos(ad,client,store,limit=config.get('photo_hash_limit',6))
                                        counts['photo_errors'].extend(photo_errors)
                                        for error in photo_errors: LOG.warning('PHOTO ERROR %s %s',error['url'],error['error'])
                                    counts['photos_hashed'] += sum(bool(p.get('dhash')) for p in ad.photos)
                                    store.save(ad); counts['saved'] += 1
                                    counts['review'] += bool(ad.review_reasons)
                                    LOG.info('SAVED %s %s price=%s area=%s review=%s %s', ad.transaction, ad.property_type, ad.price, ad.area_m2 or ad.plot_area_m2, ad.review_reasons, link)
                                except (FetchError, ValueError) as e:
                                    if isinstance(e, FetchError) and e.status in (404,410): store.unavailable(canonical(link))
                                    counts['errors'].append({'url':link,'error':str(e)}); LOG.warning('DETAIL ERROR %s %s',link,e)
                                finally:
                                    counts['processed'] += 1
                                    progress.update(key,counts,pending_pages=len(set(queue)-visited))
                            if limited: break
                        except (FetchError, ValueError) as e:
                            counts['errors'].append({'url':url,'error':str(e)}); LOG.warning('LIST ERROR %s %s',url,e)
                except KeyboardInterrupt:
                    interrupted = True
                status = 'interrupted' if interrupted else 'partial' if limited or counts['errors'] else 'ok'
                counts['limited'] = limited
                counts['elapsed_seconds']=round(time.monotonic()-started_clock,2)
                progress.update(key,counts,status=status);progress.emit()
                store.record(source['id'], search['url'], started, status, counts)
                reports.append(dict(source=source['id'], url=search['url'], status=status, **counts))
                LOG.info('FINISHED %s %s %s: %s', source['id'], search['transaction'], search['property_type'], status)
                if interrupted: return reports
    finally:
        if hasattr(client, 'session'): client.session.close()
    return reports
