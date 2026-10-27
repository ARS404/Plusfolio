"""One CPU model process, private HTTP, bounded work, no outbound requests."""
import argparse
import hashlib
import json
import os
import resource
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from functools import lru_cache

import numpy as np
import onnxruntime as ort
ort.disable_telemetry_events()
from tokenizers import Tokenizer
from download import LOCK, MODEL_ID


class Encoder:
    def __init__(self, directory, threads=2):
        directory = Path(directory)
        for remote, digest in LOCK['files'].items():
            with (directory / Path(remote).name).open('rb') as artifact:
                if hashlib.file_digest(artifact, 'sha256').hexdigest() != digest:
                    raise ValueError('Model checksum mismatch; run download.py')
        self.tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
        self.tokenizer.no_padding()
        self.tokenizer.no_truncation()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(directory / 'model_qint8_avx512_vnni.onnx'), options,
                                           providers=['CPUExecutionProvider'])
        self.inputs = {value.name for value in self.session.get_inputs()}
        self.prefix = {mode: self.tokenizer.encode(text, add_special_tokens=False).ids
                       for mode, text in [('query', 'query: '), ('document', 'passage: ')]}

    def embed(self, texts, mode):
        # Token windows cover the entire text, including the end of long solutions.
        # E5's query/passage prefix is repeated on every window.
        windows, owners = [], []
        for owner, text in enumerate(texts):
            ids = self.tokenizer.encode(text, add_special_tokens=False).ids
            if len(ids) > 12000:
                raise ValueError('Text exceeds 12000 model tokens')
            for start in range(0, max(1, len(ids)), 416):
                windows.append([0] + self.prefix[mode] + ids[start:start + 448] + [2])
                owners.append(owner)
        result = np.zeros((len(texts), 384), dtype=np.float32)
        for start in range(0, len(windows), 8):
            batch = windows[start:start + 8]
            width = max(map(len, batch))
            ids = np.ones((len(batch), width), dtype=np.int64)
            mask = np.zeros_like(ids)
            for row, tokens in enumerate(batch):
                ids[row, :len(tokens)] = tokens
                mask[row, :len(tokens)] = 1
            feeds = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': np.zeros_like(ids)}
            hidden = self.session.run(None, {key: value for key, value in feeds.items() if key in self.inputs})[0]
            pooled = (hidden * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1)[:, None]
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            for owner, vector in zip(owners[start:start + 8], pooled):
                result[owner] += vector
        result /= np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-12)
        return result.tolist()


class Handler(BaseHTTPRequestHandler):
    encoder = None
    gate = threading.BoundedSemaphore(1)

    def log_message(self, *_):
        pass  # Do not log query text, even on bad requests.

    def reply(self, status, value):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self.reply(200 if self.path == '/health' else 404,
                   {'ready': True, 'model': MODEL_ID, 'dimensions': 384, 'provider': 'CPUExecutionProvider', 'peak_rss_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2 if sys.platform == 'darwin' else 1024),1)}
                   if self.path == '/health' else {'detail': 'Not found'})

    def do_POST(self):
        if self.path != '/embed':
            return self.reply(404, {'detail': 'Not found'})
        if not self.gate.acquire(timeout=2):
            return self.reply(503, {'detail': 'Embedding worker busy'})
        try:
            self.connection.settimeout(30)
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1000000:
                raise ValueError()
            data = json.loads(self.rfile.read(size))
            texts, mode = data.get('texts'), data.get('mode', 'query')
            if (mode not in {'query', 'document'} or not isinstance(texts, list) or not 1 <= len(texts) <= 16
                    or any(not isinstance(text, str) or not text.strip() or len(text) > 30000 for text in texts)):
                raise ValueError()
            self.reply(200, {'model': MODEL_ID, 'vectors': self.encoder.embed(texts, mode)})
        except (ValueError, TypeError, UnicodeError):
            self.reply(400, {'detail': 'Invalid or too long embedding input'})
        except Exception:
            self.reply(503, {'detail': 'Embedding worker unavailable'})
        finally:
            self.gate.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default=os.environ.get('MODEL_DIRECTORY', '.local/embedding-model'))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8011)
    args = parser.parse_args()
    Handler.encoder = Encoder(args.directory, max(1, int(os.environ.get('EMBEDDING_THREADS', '2'))))
    print('Embedding worker ready:', MODEL_ID, 'CPU, port', args.port, flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
