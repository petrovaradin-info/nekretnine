"""Small in-memory photo fingerprints; originals are not stored."""
import hashlib
import requests
from io import BytesIO
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError


def fingerprint(content):
    with Image.open(BytesIO(content)) as image:
        if image.width * image.height > 20_000_000: raise ValueError('Photo exceeds 20 megapixel limit')
        image = ImageOps.exif_transpose(image).convert('RGB')
        width,height = image.size
        gray = image.convert('L')
        if min(width,height) < 80 or ImageStat.Stat(gray.resize((32,32))).stddev[0] < 8:
            return None
        small=gray.resize((9,8),Image.Resampling.LANCZOS)
        pixels=[small.getpixel((x,y)) for y in range(8) for x in range(9)]
        dhash=sum((pixels[y*9+x] > pixels[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
        small=gray.resize((8,8),Image.Resampling.LANCZOS)
        values=[small.getpixel((x,y)) for y in range(8) for x in range(8)]
        mean=sum(values)/64
        ahash=sum((v >= mean) << i for i,v in enumerate(values))
        if dhash.bit_count() < 5 or dhash.bit_count() > 59: return None
        return {'sha256':hashlib.sha256(content).hexdigest(),'dhash':f'{dhash:016x}','ahash':f'{ahash:016x}','width':width,'height':height}


def hash_distance(a,b,key):
    try: return (int(a[key],16)^int(b[key],16)).bit_count()
    except (KeyError,ValueError,TypeError): return 65


def same_photo(a,b):
    if a.get('sha256') and a.get('sha256') == b.get('sha256'): return True
    return hash_distance(a,b,'dhash') <= 4 and hash_distance(a,b,'ahash') <= 6


def unique_photos(photos):
    output=[]
    for photo in photos:
        if not photo.get('sha256') and not (photo.get('dhash') and photo.get('ahash')): continue
        if not any(same_photo(photo,other) for other in output): output.append(photo)
    return output


def photo_matches(a,b):
    left,right=unique_photos(a),unique_photos(b)
    # Maximum one-to-one matching: duplicates/crops of a single photo cannot count twice.
    matched={}
    def assign(i,seen):
        for j,photo in enumerate(right):
            if j in seen or not same_photo(left[i],photo): continue
            seen.add(j)
            if j not in matched or assign(matched[j],seen):
                matched[j]=i; return True
        return False
    return sum(assign(i,set()) for i in range(len(left)))


def enrich_photos(ad, client, store, limit=6):
    errors=[]
    for photo in ad.photos[:limit]:
        url=photo['url']
        cached=store.photo_cached(url)
        if cached is not None:
            photo.update(cached); continue
        try:
            data=client.get_image(url)
            result=fingerprint(data)
            if result:
                photo.update(result);store.save_photo(url,result)
        except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning,requests.RequestException) as e:
            errors.append({'url':url,'error':str(e)})
        except Exception as e:
            # Network/robots failure of a photo does not discard a valid listing.
            from .collector import FetchError
            if not isinstance(e,FetchError): raise
            errors.append({'url':url,'error':str(e)})
    return errors
