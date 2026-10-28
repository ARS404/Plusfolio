"""Safeguards for shared deployments and retention; no server/database required."""
import argparse,json,os,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import server,server_host,server_backup


class HostTests(unittest.TestCase):
    def values(self):return server_host.shared_values({'COMPOSE_PROJECT_NAME':'plusfolio-a','INSTANCE_ID':'abc'})
    def test_missing_tools_exit_without_package_or_daemon_commands(self):
        with patch('server_host.subprocess.run',side_effect=FileNotFoundError) as runner:
            with self.assertRaisesRegex(RuntimeError,'системные пакеты не изменялись'):server_host.tools_ready(True)
        self.assertEqual(runner.call_args.args[0][:2],['docker','info'])
        self.assertEqual(runner.call_count,1)
    def test_unsupported_cgroups_are_rejected(self):
        with patch('server_host.subprocess.run',return_value=Mock(stdout='{"CgroupDriver":"none"}')):
            with self.assertRaisesRegex(RuntimeError,'cgroups'):server_host.tools_ready()
    def test_occupied_foreign_port_is_not_taken(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            with self.assertRaisesRegex(RuntimeError,'порт занят'):server_host.port_available(listener.getsockname()[1],[])
            self.assertEqual(listener.getsockname()[0],'127.0.0.1')
    def test_owned_running_port_can_be_reused_on_update(self):
        item={'State':{'Running':True},'Config':{'Labels':{'com.docker.compose.service':'web'}},
              'HostConfig':{'PortBindings':{'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'18080'}]}}}
        with patch('server_host.socket.socket',side_effect=AssertionError('must not bind an owned port')):
            server_host.port_available(18080,[item])
    def test_other_checkout_with_same_project_is_rejected_read_only(self):
        docker=Mock(side_effect=[Mock(stdout=b'foreign-id\n'),Mock(stdout=json.dumps([{'Config':{'Labels':{
            'com.docker.compose.project.working_dir':'/someone-else/project'}}}]).encode())])
        with self.assertRaisesRegex(RuntimeError,'другой папки'):server_host.project_containers(docker,self.values(),ROOT)
        self.assertEqual([call.args[0] for call in docker.call_args_list],['ps','inspect'])
    def test_shared_defaults_and_legacy_conversion(self):
        values=server_host.shared_values({'COMPOSE_PROJECT_NAME':'plusfolio-a','BIND_ADDRESS':'0.0.0.0','HTTP_PORT':'80'},legacy=True)
        self.assertNotIn('BIND_ADDRESS',values);self.assertEqual(values['LOCAL_PORT'],'18080')
        self.assertEqual(values['PLUSFOLIO_APP_IMAGE'],'plusfolio-app:local')
        self.assertEqual(self.values()['PLUSFOLIO_APP_IMAGE'],'plusfolio-a-app:local')
    def test_privileged_ports_invalid_budgets_and_retention_are_rejected(self):
        for field,value in [('LOCAL_PORT','443'),('BUILD_CPUS','0'),('BUILD_MEMORY','unlimited'),('BACKUP_KEEP_MIN','1')]:
            with self.subTest(field=field),self.assertRaises(ValueError):server_host.shared_values({**self.values(),field:value})
    def test_runtime_limits_and_public_binding_are_required(self):
        base={'mem_limit':256*1048576,'memswap_limit':256*1048576,'pids_limit':32,'cpus':.25,
              'ports':[{'host_ip':'127.0.0.1','target':8000,'published':'18080'}]}
        self.assertEqual(server_host.check_limits({'services':{'web':base}})['memory_mib'],256)
        for changes in [{'cpus':0},{'pids_limit':0},{'memswap_limit':-1},
                        {'ports':[{'host_ip':'0.0.0.0','target':8000,'published':'18080'}]}]:
            with self.subTest(changes=changes),self.assertRaises(RuntimeError):server_host.check_limits({'services':{'web':{**base,**changes}}})
    def test_builder_is_bounded_and_default_builder_is_never_selected(self):
        calls=[]
        def docker(*args,**kwargs):calls.append((args,kwargs));return Mock(stdout=b'default\n')
        name=server_host.build_images(docker,self.values(),ROOT)
        created=next(args for args,_ in calls if args[:2]==('buildx','create'))
        self.assertIn('cpu-quota=100000',created);self.assertIn('memory=1024m',created)
        self.assertNotIn('--use',created);self.assertEqual(calls[-1][0],('buildx','stop',name))
    def test_failed_build_also_stops_only_its_builder(self):
        calls=[]
        def docker(*args,**kwargs):
            calls.append(args)
            if args[:2]==('buildx','bake'):raise subprocess.CalledProcessError(1,args)
            return Mock(stdout=b'default\n')
        with self.assertRaises(subprocess.CalledProcessError):server_host.build_images(docker,self.values(),ROOT)
        self.assertEqual(calls[-1][:2],('buildx','stop'));self.assertNotEqual(calls[-1][-1],'default')
    def test_compose_project_cannot_be_overridden_by_ambient_environment(self):
        with patch('server.read_env',return_value=self.values()),patch.dict(os.environ,{'COMPOSE_PROJECT_NAME':'foreign'}),patch('server.subprocess.run') as runner:
            server.compose('stop')
        call=runner.call_args
        self.assertEqual(call.kwargs['env']['COMPOSE_PROJECT_NAME'],'plusfolio-a')
        self.assertIn('--project-name',call.args[0]);self.assertIn('plusfolio-a',call.args[0])
    def test_init_without_tools_does_not_create_configuration(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(server,'STATE',Path(temporary)/'absent'),patch('server_host.tools_ready',side_effect=RuntimeError('missing tools')):
            with self.assertRaises(RuntimeError):server.run(argparse.Namespace(command='init',config=None,no_build=False))
            self.assertFalse(server.STATE.exists())


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name);self.now=time.time()
        self.policy={'days':14,'count':4,'bytes':40,'keep':2}
    def make(self,number,age=0,size=10):
        path=self.directory/f'plusfolio-202610{number:02}T000000000000Z.tar.gz.age'
        path.write_bytes(b'x'*size);os.utime(path,(self.now-age*86400,)*2);return path
    def test_age_count_and_byte_limits_preserve_two_latest(self):
        for n in range(1,7):self.make(n,age=20 if n<3 else 0)
        result=server_backup.prune_backups(self.directory,self.policy,self.now)
        self.assertEqual(result,{'removed':2,'kept':4,'bytes':40})
        self.assertTrue((self.directory/'plusfolio-20261006T000000000000Z.tar.gz.age').exists())
    def test_never_removes_last_two_even_if_old_or_above_budget(self):
        files=[self.make(n,age=90,size=50) for n in range(1,4)]
        server_backup.prune_backups(self.directory,self.policy,self.now)
        self.assertFalse(files[0].exists());self.assertTrue(files[1].exists());self.assertTrue(files[2].exists())
    def test_newest_archives_are_kept_even_when_file_mtime_was_copied(self):
        self.make(1);self.make(2);self.make(3,age=90);self.make(4,age=90)
        result=server_backup.prune_backups(self.directory,{**self.policy,'count':2},self.now)
        self.assertEqual(result['kept'],2);self.assertTrue((self.directory/'plusfolio-20261004T000000000000Z.tar.gz.age').exists())
    def test_foreign_files_symlinks_and_active_partials_are_untouched(self):
        foreign=self.directory/'other-app.age';foreign.write_bytes(b'foreign')
        link=self.directory/'plusfolio-20000101T000000000000Z.tar.gz.age';link.symlink_to(foreign)
        partial=self.directory/'plusfolio-20000101T000000000000Z.tar.gz.partial';partial.write_bytes(b'active')
        self.make(1);self.make(2)
        server_backup.prune_backups(self.directory,self.policy,self.now)
        self.assertEqual(foreign.read_bytes(),b'foreign');self.assertTrue(link.is_symlink());self.assertTrue(partial.exists())
    def test_stale_interrupted_partial_is_removed(self):
        path=self.directory/'plusfolio-20000101T000000000000Z.tar.gz.partial';path.write_bytes(b'stale');os.utime(path,(self.now-90000,)*2)
        server_backup.prune_backups(self.directory,self.policy,self.now);self.assertFalse(path.exists())
    def test_failed_backup_does_not_prune_existing_copies(self):
        self.make(1,age=90)
        with patch('server_backup.Path',side_effect=lambda value: self.directory if value=='/backups' else Path(value)),patch('server_backup._backup',side_effect=RuntimeError('failed')),patch('server_backup.prune_backups') as prune:
            with self.assertRaises(RuntimeError):server_backup.backup()
        prune.assert_not_called()


if __name__=='__main__':unittest.main()
