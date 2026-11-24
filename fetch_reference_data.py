"""Download read-only reference data; retain failures and provenance."""
from pathlib import Path
import concurrent.futures
import ftplib
import gzip
import hashlib
import io
import json
import urllib.request
import zlib

ROOT=Path(__file__).resolve().parent
DEST=ROOT/'reference_data'

def whu():
    log=[]
    ftp=ftplib.FTP()
    try:
        ftp.connect('igs.gnsswhu.cn',21,timeout=20);ftp.login()
        for path in ['/pub/gps/data/daily/2026/309/26p','/pub/gps/data/daily/2026/brdc',
                     '/pub/gnss/data/daily/2026/309/26p']:
            try:
                names=ftp.nlst(path)
                log.append(dict(url='ftp://igs.gnsswhu.cn'+path,listing=names))
                matches=[n for n in names if '2026309' in n and 'MN.rnx' in n]
                for name in matches[:2]:
                    buf=io.BytesIO();ftp.retrbinary('RETR '+(name if '/' in name else path+'/'+name),buf.write)
                    data=buf.getvalue();target=DEST/Path(name).name;target.write_bytes(data)
                    log.append(dict(url='ftp://igs.gnsswhu.cn'+path+'/'+Path(name).name,
                                    file=str(target),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
                    if target.suffix=='.gz':target.with_suffix('').write_bytes(gzip.decompress(data))
                    return log
            except Exception as e:log.append(dict(path=path,error=repr(e)))
    except Exception as e:log.append(dict(host='igs.gnsswhu.cn',error=repr(e)))
    finally:
        try:ftp.close()
        except Exception:pass
    return log

def http(url,name):
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=25) as f:data=f.read()
        if name.endswith('.gz'):
            plain=gzip.decompress(data)
            if b'RINEX VERSION / TYPE' not in plain[:200]:raise ValueError('Not RINEX')
        target=DEST/name;target.write_bytes(data)
        if name.endswith('.gz'):target.with_suffix('').write_bytes(plain)
        return dict(url=url,file=str(target),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    except Exception as e:return dict(url=url,error=repr(e))

def whu_web():
    DEST.mkdir(exist_ok=True)
    query={'data':{'type':'gbxl','filename':'','start_time':'2026-11-05','end_time':'2026-11-05'},'start':0,'limit':100}
    listing_path=DEST/'whu_broadcast_listing.json'
    if not listing_path.exists():
        req=urllib.request.Request('http://www.igs.gnsswhu.cn/index.php/igs/gbxlList',
            data=json.dumps(query).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=30) as f:listing_path.write_bytes(f.read())
    listing=json.loads(listing_path.read_text(encoding='utf-8-sig'))
    receipt=[]
    for row in listing['rows']:
        if not row['filename'].startswith(('BRDC00IGS','BRDM00DLR')):continue
        url=f'http://www.igs.gnsswhu.cn/index.php/igs/download?year={row["year"]}&id={row["id"]}'
        raw=DEST/('WHU_'+row['filename'])
        if not raw.exists():
            with urllib.request.urlopen(url,timeout=40) as f:raw.write_bytes(f.read())
        body=raw.read_bytes();decoder=zlib.decompressobj(31)
        plain=decoder.decompress(body)+decoder.flush()
        if not decoder.eof:raise ValueError('Incomplete gzip member')
        member=body[:len(body)-len(decoder.unused_data)]
        if hashlib.md5(member).hexdigest()!=row['hash']:raise ValueError('WHU listing MD5 mismatch')
        clean=DEST/('CLEAN_'+raw.name);clean.write_bytes(member)
        unpacked=raw.with_suffix('');unpacked.write_bytes(plain)
        receipt.append(dict(url=url,filename=row['filename'],http_response=str(raw),
            compressed_file=str(clean),rinex_file=str(unpacked),
            md5=hashlib.md5(member).hexdigest(),listing_md5=row['hash'],
            sha256=hashlib.sha256(member).hexdigest(),rinex_sha256=hashlib.sha256(plain).hexdigest(),
            gzip_member_bytes=len(member),trailing_html_bytes=len(decoder.unused_data),
            gzip_integrity_valid=True,listing_md5_valid=True))
    (DEST/'download_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt

if __name__=='__main__':
    print(json.dumps(whu_web(),indent=2))

if False:  # Retain initial FTP/mirror diagnostics as callable helpers only.
    DEST.mkdir(exist_ok=True)
    logs=whu()
    if not any('file' in x for x in logs):
        urls=[
          ('https://igs.bkg.bund.de/root_ftp/IGS/BRDC/2026/309/BRDC00WRD_S_20263090000_01D_MN.rnx.gz','BRDC00WRD_S_20263090000_01D_MN.rnx.gz'),
          ('https://igs.bkg.bund.de/root_ftp/IGS/BRDC/2026/309/BRDC00IGS_R_20263090000_01D_MN.rnx.gz','BRDC00IGS_R_20263090000_01D_MN.rnx.gz'),
          ('https://garner.ucsd.edu/pub/rinex/2026/309/BRDC00IGS_R_20263090000_01D_MN.rnx.gz','UCSD_BRDC00IGS_R_20263090000_01D_MN.rnx.gz'),
          ('http://www.igs.gnsswhu.cn/index.php','whu_index.html')]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            logs+=list(pool.map(lambda v:http(*v),urls))
    (DEST/'download_log.json').write_text(json.dumps(logs,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(logs,ensure_ascii=False,indent=2))
