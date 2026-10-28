import json,os,socket,sys,time,urllib.request,urllib.parse
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
    if os.environ.get('REDIS_URL'):
        # Django's default Redis cache stores integer heartbeats as ASCII.
        # Avoid importing the application during a low-CPU health probe.
        # This service uses the private, unauthenticated Redis from compose.yml.
        address=urllib.parse.urlsplit(os.environ['REDIS_URL'])
        if address.scheme!='redis' or address.username or address.password or address.path not in {'','/0'}:raise SystemExit(1)
        key=(':1:worker:'+kind).encode()
        command=b'*2\r\n$3\r\nGET\r\n$'+str(len(key)).encode()+b'\r\n'+key+b'\r\n'
        with socket.create_connection((address.hostname,address.port or 6379),timeout=2) as client:
            client.sendall(command);stream=client.makefile('rb');header=stream.readline(64)
            if not header.startswith(b'$'):raise SystemExit(1)
            size=int(header[1:].strip())
            if not 1<=size<=20:raise SystemExit(1)
            timestamp=int(stream.read(size))
    else:
        sys.path.insert(0,str(ROOT/'backend'));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
        import django;django.setup()
        from django.core.cache import cache
        timestamp=cache.get('worker:'+kind,0)
    if time.time()-timestamp>60:raise SystemExit(1)
