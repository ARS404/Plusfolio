"""Prepare immutable ONNX artifacts. Serving never contacts the model registry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

LOCK = json.loads(Path(__file__).with_name('model.lock.json').read_text())
MODEL_ID = 'e5-small-int8-' + LOCK['revision'][:12] + '-chunk448-v1'


def prepare(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for remote, digest in LOCK['files'].items():
        target = directory / Path(remote).name
        if target.exists() and hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() == digest:
            continue
        partial = target.with_suffix(target.suffix + '.partial')
        url = f"https://huggingface.co/{LOCK['repository']}/resolve/{LOCK['revision']}/{remote}"
        print('Downloading', remote, flush=True)
        try:
            with urllib.request.urlopen(url, timeout=120) as source, partial.open('wb') as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            with partial.open('rb') as downloaded:
                if hashlib.file_digest(downloaded, 'sha256').hexdigest() != digest:
                    raise ValueError('Model checksum mismatch')
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    print('Ready:', MODEL_ID, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default=str(Path(__file__).resolve().parents[1] / '.local' / 'embedding-model'))
    prepare(parser.parse_args().directory)
