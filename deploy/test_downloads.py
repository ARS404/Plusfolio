import hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from download_asset import download
from install_locked import locked,install

class Reply(io.BytesIO):
    def __init__(self,value,status=200,headers=None):super().__init__(value);self.status=status;self.headers=headers or {}

class AssetTests(unittest.TestCase):
    def test_parallel_ranges_and_verified_content(self):
        value=(b'verifiable-asset-'*200000);digest=hashlib.sha256(value).hexdigest();seen=[]
        def open(request,timeout=0):
            header=request.headers['Range'];start,end=map(int,header.removeprefix('bytes=').split('-'));seen.append((start,end))
            return Reply(value[start:end+1],206,{'Content-Range':f'bytes {start}-{end}/{len(value)}'})
        with tempfile.TemporaryDirectory() as root,patch('urllib.request.urlopen',side_effect=open):
            target=Path(root)/'asset';download('https://example.test/asset',target,digest,len(value),workers=4)
            self.assertEqual(target.read_bytes(),value);self.assertGreater(len(seen),2)
    def test_ignored_range_uses_safe_serial_fallback(self):
        value=b'a'*3000000
        with tempfile.TemporaryDirectory() as root,patch('urllib.request.urlopen',side_effect=lambda *args,**kw:Reply(value)):
            target=Path(root)/'asset';download('https://example.test/asset',target,hashlib.sha256(value).hexdigest(),len(value))
            self.assertEqual(target.stat().st_size,len(value))
    def test_wrong_hash_never_publishes_or_retains_partial(self):
        with tempfile.TemporaryDirectory() as root,patch('urllib.request.urlopen',return_value=Reply(b'changed')):
            target=Path(root)/'asset'
            with self.assertRaises(ValueError):download('https://example.test/asset',target,'0'*64,size=7,workers=1)
            self.assertFalse(target.exists());self.assertEqual(list(Path(root).iterdir()),[])
    def test_valid_existing_asset_does_not_contact_registry(self):
        with tempfile.TemporaryDirectory() as root,patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            target=Path(root)/'asset';target.write_bytes(b'known');download('https://example.test/asset',target,hashlib.sha256(b'known').hexdigest())
    def test_lock_parser_rejects_unpinned_or_conflicting_packages(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);(root/'base').write_text('numpy==2.5.4\n');(root/'server').write_text('-r base\nredis==8.1.0\n')
            self.assertEqual(locked(root/'server'),{'numpy':'2.5.4','redis':'8.1.0'})
            (root/'server').write_text('-r base\nnumpy==2.4.0\n')
            with self.assertRaises(ValueError):locked(root/'server')
            (root/'server').write_text('numpy>=2\n')
            with self.assertRaises(ValueError):locked(root/'server')

    def test_lock_includes_reject_cycles_and_normalized_name_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'one').write_text('-r two\n');(root/'two').write_text('-r one\n')
            with self.assertRaisesRegex(ValueError,'Cyclic'):locked(root/'one')
            (root/'one').write_text('Example_Package==1.0\nexample-package==2.0\n')
            with self.assertRaisesRegex(ValueError,'Conflicting'):locked(root/'one')
            (root/'one').write_text('Example_Package==1.0\nexample-package==1.0\n')
            self.assertEqual(locked(root/'one'),{'Example_Package':'1.0'})

    def test_wheel_cache_reuses_verified_bytes_and_repairs_tampering(self):
        payload=b'synthetic public wheel';digest=hashlib.sha256(payload).hexdigest()
        filename='example_package-1.0-py3-none-any.whl';downloads=[]
        metadata={'urls':[{'packagetype':'bdist_wheel','filename':filename,'digests':{'sha256':digest},
                           'url':'https://example.test/wheel','size':len(payload)}]}
        def open(url,timeout=0):
            if url.startswith('https://pypi.org/'):
                return Reply(json.dumps(metadata).encode())
            downloads.append(url);return Reply(payload)
        def pip(command,**kwargs):
            if '--find-links' in command:
                folder=Path(command[command.index('--find-links')+1])
                self.assertEqual(sorted(p.name for p in folder.glob('*.whl')),[filename])
                self.assertEqual((folder/filename).read_bytes(),payload)
                self.assertIn('--require-hashes',command);self.assertIn('--no-index',command)
        with tempfile.TemporaryDirectory() as directory,patch('urllib.request.urlopen',side_effect=open),patch('install_locked.subprocess.run',side_effect=pip):
            root=Path(directory);lock=root/'lock';lock.write_text('example-package==1.0\n');cache=root/'cache'
            install(lock,cache);install(lock,cache)
            self.assertEqual(len(downloads),1)
            cached=cache/digest/filename;cached.write_bytes(b'tampered')
            (cache/'unrelated-1.0-py3-none-any.whl').write_bytes(b'unrelated cache entry')
            install(lock,cache)
            self.assertEqual(len(downloads),2);self.assertEqual(cached.read_bytes(),payload)

if __name__=='__main__':unittest.main()
