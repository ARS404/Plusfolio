"""Compiler admission limits, exercised without a real compiler or network listener."""
import importlib.util,io,json,threading
from unittest.mock import Mock,patch
from django.conf import settings
from django.test import SimpleTestCase


def service():
    spec=importlib.util.spec_from_file_location('tex_service_limits',settings.BASE_DIR/'scripts/tex_service.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class CompilerAdmissionTests(SimpleTestCase):
    def test_handler_cap_rejects_excess_connections_and_releases_after_failure(self):
        module=service();release=threading.Event();started=threading.Event();resumed=threading.Event();lock=threading.Lock();threads=[]
        def handler(request,address,server):
            with lock:
                threads.append(threading.current_thread())
                if len(threads)==module.MAX_CLIENTS:started.set()
                if len(threads)==module.MAX_CLIENTS+1:resumed.set()
            if not release.wait(2):raise RuntimeError('test synchronization timeout')
            raise ValueError('synthetic handler failure')
        class UnboundServer(module.Server):
            def server_bind(self):pass
            def server_activate(self):pass
        with UnboundServer('unused',handler) as server,patch.object(server,'handle_error'):
            try:
                for _ in range(module.MAX_CLIENTS):server.process_request(Mock(),'local')
                self.assertTrue(started.wait(2))
                extra=Mock();server.process_request(extra,'local')
                extra.close.assert_called_once();self.assertEqual(len(threads),module.MAX_CLIENTS)
            finally:
                release.set()
                for thread in threads:thread.join(2)
            # Failed handlers returned their slots: another real dispatch must run.
            server.process_request(Mock(),'local')
            self.assertTrue(resumed.wait(2))
            for thread in threads:thread.join(2)
            self.assertEqual(len(threads),module.MAX_CLIENTS+1)
            self.assertTrue(all(not thread.is_alive() for thread in threads))

    def handle(self,module,payload):
        handler=module.Handler.__new__(module.Handler)
        handler.connection=Mock();handler.rfile=io.BytesIO(str(len(payload)).encode()+b'\n'+payload);handler.wfile=io.BytesIO()
        handler.handle();frame=handler.wfile.getvalue().split(b'\n',1)
        self.assertEqual(int(frame[0]),len(frame[1]));return json.loads(frame[1])

    def test_busy_large_projects_are_not_decoded_and_health_remains_available(self):
        module=service();payload=json.dumps({'main.tex':'x'*4096}).encode()
        module.GATE.acquire()
        try:
            with patch.object(module.json,'loads',wraps=json.loads) as decode,patch.object(module,'compile_project') as compile:
                # Parse the response after inspecting the service's decode calls.
                handler=module.Handler.__new__(module.Handler)
                handler.connection=Mock();handler.rfile=io.BytesIO(str(len(payload)).encode()+b'\n'+payload);handler.wfile=io.BytesIO()
                handler.handle();decode.assert_not_called();compile.assert_not_called()
            self.assertTrue(json.loads(handler.wfile.getvalue().split(b'\n',1)[1])['busy'])
            self.assertEqual(self.handle(module,b'{"health":true}'),{'ok':True})
        finally:module.GATE.release()
        with patch.object(module,'compile_project',return_value={'pdf':'synthetic'}) as compile:
            self.assertEqual(self.handle(module,payload),{'pdf':'synthetic'})
            self.assertEqual(compile.call_args.args[0],{'main.tex':'x'*4096})
        with patch.object(module,'compile_project',side_effect=ValueError('synthetic compiler failure')):
            self.assertIn('error',self.handle(module,payload))
        self.assertTrue(module.GATE.acquire(blocking=False));module.GATE.release()
