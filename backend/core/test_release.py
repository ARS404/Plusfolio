"""Product versions stay synchronized without changing domain or API versions."""
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from .release import ROOT, build_metadata, read_release, release_info, source_revision, validate_release


def release_tools():
    spec=importlib.util.spec_from_file_location('plusfolio_release_tools',ROOT/'scripts/release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class ReleaseTests(SimpleTestCase):
    def test_checkout_and_frontend_mirrors_use_the_same_version(self):
        self.assertEqual(release_tools().check(),read_release())
        self.assertEqual(release_info()['version'],read_release()['version'])

    def test_invalid_versions_and_statuses_are_rejected(self):
        for version in ['1.0','01.0.0','1.0.0-01','1.0.0+','1.0.0/other',None]:
            with self.subTest(version=version),self.assertRaises(ValueError):
                validate_release({'version':version,'status':'development'})
        for status in ['stable',[],None]:
            with self.subTest(status=status),self.assertRaises(ValueError):
                validate_release({'version':'1.0.0','status':status})
        self.assertEqual(validate_release({'version':'1.1.0-rc.1','status':'development'})['version'],'1.1.0-rc.1')
        with self.assertRaises(ValueError):validate_release({'version':'1.1.0-rc.1','status':'released'})

    def test_version_bump_synchronizes_mirrors_and_checks_stable_tags(self):
        tools=release_tools()
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'frontend').mkdir()
            (root/'frontend/package.json').write_text('{"version":"0.1.0"}')
            (root/'frontend/package-lock.json').write_text('{"version":"0.1.0","packages":{"":{"version":"0.1.0"}}}')
            tools.set_release('1.2.3',root=root)
            self.assertEqual(tools.check(root)['version'],'1.2.3')
            with self.assertRaises(ValueError):tools.check(root,'v1.2.3')
            tools.set_release('1.2.3','released',root)
            self.assertEqual(tools.check(root,'v1.2.3')['status'],'released')
            with self.assertRaises(ValueError):tools.check(root,'v1.2.4')
            (root/'frontend/package.json').write_text('{"version":"9.0.0"}')
            with self.assertRaises(ValueError):tools.check(root)

    def test_archives_work_without_git_and_only_a_public_revision_is_exposed(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'release.json').write_text('{"version":"1.0.0","status":"development"}')
            self.assertEqual(source_revision(root),'unknown')
            with patch.dict(os.environ,{'PLUSFOLIO_REVISION':'a'*40}):
                self.assertEqual(build_metadata(root)['revision'],'a'*40)
            with patch.dict(os.environ,{'PLUSFOLIO_REVISION':'invalid metadata'}):
                self.assertEqual(build_metadata(root)['revision'],'unknown')

    def test_health_and_openapi_report_product_identity(self):
        from .api_reference import schema_for
        from . import health
        release=release_info()
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'frontend/dist').mkdir(parents=True)
            (root/'frontend/dist/index.html').write_text('<html></html>')
            with override_settings(BASE_DIR=root,DEMO=True),patch('core.health.connection') as database:
                response=health.ready(SimpleNamespace(method='GET'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(json.loads(response.content)['release'],release)
        database.cursor.assert_called_once()
        spec=schema_for(SimpleNamespace(roles=['admin']))
        self.assertEqual(spec['info']['version'],release['version'])
        self.assertEqual(spec['x-plusfolio-release'],release)
        self.assertEqual(spec['servers'][0]['url'],'/api/v1')
