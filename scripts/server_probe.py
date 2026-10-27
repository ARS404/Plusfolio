import json,os,socket,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
kind=sys.argv[1]
if kind=='tex':
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(2);client.connect(os.environ['PLUSFOLIO_TEX_SOCKET']);payload=json.dumps({'health':True}).encode();client.sendall(str(len(payload)).encode()+b'\n'+payload)
        stream=client.makefile('rb');size=int(stream.readline(32));reply=json.loads(stream.read(size))
        if reply.get('ok') is not True:raise SystemExit(1)
elif kind=='web':
    with urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=6) as response:
        if json.load(response).get('ok') is not True:raise SystemExit(1)
elif kind in {'mail','index'}:
    sys.path.insert(0,str(ROOT/'backend'));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    import django;django.setup()
    from django.core.cache import cache
    if time.time()-cache.get('worker:'+kind,0)>60:raise SystemExit(1)
