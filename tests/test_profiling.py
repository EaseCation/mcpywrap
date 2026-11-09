"""性能分析：工具清单、多镜像下载、校验解压、端点握手、报告摘要与 CLI；不启动游戏或真实 Tracy。"""
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.profiling import analysis, endpoint, tools

SUFFIX = '.exe' if os.name == 'nt' else ''
TAG = 'macos-arm64'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_bundle(path, tag=TAG, tamper=None, extra=None):
    files = {name + SUFFIX: ('#!' + name).encode() for name in tools.EXECUTABLES}
    info = {'schema': 1, 'tracy_version': '0.11.1', 'protocol': 69, 'build': '1', 'platform': tag,
            'files': {name: sha(data) for name, data in files.items()}}
    if tamper:
        files[tamper] = b'changed'
    with zipfile.ZipFile(path, 'w') as bundle:
        for name, data in files.items():
            member = zipfile.ZipInfo('mcpy-tracy/' + name)
            member.external_attr = 0o100755 << 16
            bundle.writestr(member, data)
        bundle.writestr('mcpy-tracy/BUILDINFO.json', json.dumps(info))
        for name, data in (extra or {}).items():
            bundle.writestr(name, data)
    data = Path(path).read_bytes()
    return {'filename': Path(path).name, 'size': len(data), 'sha256': sha(data)}


class ToolsEnvironment(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.mirror = self.temp / 'mirror'
        self.mirror.mkdir()
        self.manifest = self.temp / 'tools.json'
        patches = [patch.dict(os.environ, {'MCPY_ENGINE_HOME': str(self.temp / 'home'),
                                           tools.MANIFEST_ENV: str(self.manifest)}),
                   patch.object(tools, 'platform_tag', return_value=TAG)]
        os.environ.pop(tools.MIRROR_ENV, None)
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def write_manifest(self, entry, mirrors=None):
        data = {'schema': 1, 'tracy_version': '0.11.1', 'protocol': 69, 'build': '1',
                'mirrors': mirrors if mirrors is not None else [str(self.mirror)], 'platforms': {TAG: entry}}
        self.manifest.write_text(json.dumps(data))
        return data


class ManifestTests(ToolsEnvironment):
    def test_builtin_manifest_is_valid_and_pins_tracy_protocol(self):
        with patch.dict(os.environ, {tools.MANIFEST_ENV: ''}):
            os.environ.pop(tools.MANIFEST_ENV)
            data = tools.manifest()
        self.assertEqual((data['tracy_version'], data['protocol']), ('0.11.1', 69))

    def test_rejects_unsafe_filename_and_bad_hash(self):
        for entry in ({'filename': '../x.zip', 'size': 1, 'sha256': 'a' * 64},
                      {'filename': 'x.zip', 'size': 1, 'sha256': 'xyz'}):
            self.write_manifest(entry)
            with self.assertRaises(EngineError) as raised:
                tools.manifest()
            self.assertEqual(raised.exception.code, 'profiler_manifest_invalid')

    def test_environment_mirror_takes_precedence(self):
        data = self.write_manifest({'filename': 'a.zip', 'size': 1, 'sha256': 'a' * 64}, ['https://one.example/x/'])
        with patch.dict(os.environ, {tools.MIRROR_ENV: 'https://cn.example/t, https://one.example/x/'}):
            urls = tools.sources(data, data['platforms'][TAG])
        self.assertEqual(urls, ['https://cn.example/t/a.zip', 'https://one.example/x/a.zip'])

    def test_unsupported_platform_reports_clearly(self):
        self.write_manifest({'filename': 'a.zip', 'size': 1, 'sha256': 'a' * 64})
        with patch.object(tools, 'platform_tag', return_value=None):
            with self.assertRaises(EngineError) as raised:
                tools.install()
        self.assertEqual(raised.exception.code, 'unsupported_platform')


class DownloadTests(ToolsEnvironment):
    entry = {'filename': 'a.zip', 'size': 3, 'sha256': 'a' * 64}

    def test_falls_back_to_next_mirror(self):
        calls = []

        def fetch(url, target, expected, size, progress=None):
            calls.append(url)
            if 'bad' in url:
                raise EngineError('网络下载失败', 'download_failed')
            return Path(target)
        with patch('mcpywrap_core.engines.install.fetch', side_effect=fetch):
            result = tools.download(['https://bad/a.zip', 'https://good/a.zip'], self.temp / 'a.zip', self.entry,
                                    sleep=lambda s: None)
        self.assertEqual(result, self.temp / 'a.zip')
        self.assertEqual(calls, ['https://bad/a.zip', 'https://good/a.zip'])

    def test_retries_rounds_with_backoff_then_keeps_progress_hint(self):
        sleeps = []
        part = self.temp / 'a.zip.part'
        part.write_bytes(b'x')
        with patch('mcpywrap_core.engines.install.fetch', side_effect=EngineError('断开', 'download_failed')):
            with self.assertRaises(EngineError) as raised:
                tools.download(['https://a/a.zip', 'https://b/a.zip'], self.temp / 'a.zip', self.entry, sleep=sleeps.append)
        self.assertEqual(raised.exception.code, 'download_failed')
        self.assertEqual(sleeps, list(tools.BACKOFF))
        self.assertEqual(len(raised.exception.details['attempts']), 6)
        self.assertTrue(part.exists(), '网络错误后保留续传进度')

    def test_integrity_error_discards_partial_and_tries_next(self):
        part = self.temp / 'a.zip.part'

        def fetch(url, target, expected, size, progress=None):
            if 'bad' in url:
                part.write_bytes(b'xxx')
                raise EngineError('摘要不符', 'integrity_error')
            self.assertFalse(part.exists())
            return Path(target)
        with patch('mcpywrap_core.engines.install.fetch', side_effect=fetch):
            tools.download(['https://bad/a.zip', 'https://ok/a.zip'], self.temp / 'a.zip', self.entry, sleep=lambda s: None)

    def test_storage_errors_stop_immediately(self):
        with patch('mcpywrap_core.engines.install.fetch', side_effect=EngineError('磁盘满', 'download_storage_failed')):
            with self.assertRaises(EngineError) as raised:
                tools.download(['https://a/a.zip', 'https://b/a.zip'], self.temp / 'a.zip', self.entry, sleep=lambda s: None)
        self.assertEqual(raised.exception.code, 'download_storage_failed')


class InstallTests(ToolsEnvironment):
    def test_installs_from_local_mirror_and_is_idempotent(self):
        entry = make_bundle(self.mirror / 'tools.zip')
        self.write_manifest(entry)
        result = tools.install()
        self.assertTrue(result['changed'])
        directory = Path(result['path'])
        for name in tools.EXECUTABLES:
            path = directory / (name + SUFFIX)
            self.assertTrue(path.is_file())
            if os.name != 'nt':
                self.assertTrue(os.access(path, os.X_OK))
        self.assertTrue(tools.status()['installed'])
        self.assertEqual(tools.require('tracy-capture'), directory / ('tracy-capture' + SUFFIX))
        self.assertFalse(tools.install()['changed'])

    def test_import_from_archive_requires_matching_digest(self):
        entry = make_bundle(self.mirror / 'tools.zip')
        self.write_manifest(dict(entry, sha256='0' * 64), mirrors=[])
        with self.assertRaises(EngineError) as raised:
            tools.install(from_archive=self.mirror / 'tools.zip')
        self.assertEqual(raised.exception.code, 'integrity_error')
        self.write_manifest(entry, mirrors=[])
        self.assertTrue(tools.install(from_archive=self.mirror / 'tools.zip')['installed'])

    def test_rejects_tampered_binary_and_keeps_no_partial_install(self):
        entry = make_bundle(self.mirror / 'tools.zip', tamper='tracy-capture' + SUFFIX)
        self.write_manifest(entry)
        with self.assertRaises(EngineError) as raised:
            tools.install()
        self.assertEqual(raised.exception.code, 'integrity_error')
        self.assertFalse(tools.status()['installed'])
        self.assertEqual([p for p in Path(tools.install_dir()).parent.iterdir()] if Path(tools.install_dir()).parent.exists() else [], [])

    def test_rejects_paths_outside_bundle_and_wrong_platform(self):
        entry = make_bundle(self.mirror / 'tools.zip', extra={'evil.txt': b'x'})
        self.write_manifest(entry)
        with self.assertRaises(EngineError) as raised:
            tools.install()
        self.assertEqual(raised.exception.code, 'unsafe_archive')
        entry = make_bundle(self.mirror / 'other.zip', tag='windows-x64')
        self.write_manifest(entry)
        with self.assertRaises(EngineError) as raised:
            tools.install()
        self.assertEqual(raised.exception.code, 'integrity_error')

    def test_unpublished_platform_accepts_explicit_local_import_only(self):
        archive = self.mirror / 'linux.zip'
        make_bundle(archive, tag='linux-arm64')
        self.write_manifest(make_bundle(self.mirror / 'tools.zip'), mirrors=[])
        with patch.object(tools, 'platform_tag', return_value='linux-arm64'):
            with self.assertRaises(EngineError) as raised:
                tools.install()
            self.assertEqual(raised.exception.code, 'unsupported_platform')
            self.assertIn('--from', raised.exception.hint)
            with self.assertRaises(EngineError) as raised:
                tools.require('tracy-capture')
            self.assertEqual(raised.exception.code, 'profiler_tools_missing')
            result = tools.install(from_archive=archive)
            self.assertEqual((result['changed'], result['source']), (True, 'local-import'))
            status = tools.status()
            self.assertEqual((status['available'], status['installed'], status['source']), (False, True, 'local-import'))
            self.assertTrue(tools.require('tracy-capture').is_file())
            self.assertFalse(tools.install(from_archive=archive)['changed'])

    def test_local_import_still_verifies_bundle_identity(self):
        self.write_manifest(make_bundle(self.mirror / 'tools.zip'), mirrors=[])
        with patch.object(tools, 'platform_tag', return_value='linux-arm64'):
            make_bundle(self.mirror / 'wrong.zip', tag='macos-arm64')
            with self.assertRaises(EngineError) as raised:
                tools.install(from_archive=self.mirror / 'wrong.zip')
            self.assertEqual(raised.exception.code, 'integrity_error')
            make_bundle(self.mirror / 'tampered.zip', tag='linux-arm64', tamper='tracy-capture' + SUFFIX)
            with self.assertRaises(EngineError) as raised:
                tools.install(from_archive=self.mirror / 'tampered.zip')
            self.assertEqual(raised.exception.code, 'integrity_error')
            self.assertFalse(tools.status()['installed'])

    def test_missing_tools_point_to_install_command(self):
        self.write_manifest(make_bundle(self.mirror / 'tools.zip'))
        with self.assertRaises(EngineError) as raised:
            tools.require('tracy-profiler')
        self.assertEqual(raised.exception.code, 'profiler_tools_missing')
        self.assertIn('mcpy profile install', raised.exception.hint)


class FakeTracy:
    """只回应握手首字节的本机监听；reply=None 表示接受连接但不应答（已有分析器）。"""

    def __init__(self, reply):
        self.reply = reply
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(4)
        self.port = self.server.getsockname()[1]
        self.received = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            conn, _ = self.server.accept()
        except OSError:
            return
        with conn:
            self.received.append(conn.recv(12))
            if self.reply is not None:
                conn.sendall(bytes([self.reply]))
            else:
                threading.Event().wait(1)

    def close(self):
        self.server.close()


class EndpointTests(unittest.TestCase):
    def check(self, reply, expected):
        fake = FakeTracy(reply)
        try:
            self.assertEqual(endpoint.handshake(fake.port, 69, timeout=0.3), expected)
            if reply is not None:
                self.assertEqual(fake.received[0], b'TracyPrf' + (69).to_bytes(4, 'little'))
        finally:
            fake.close()

    def test_handshake_states(self):
        self.check(1, 'welcome')
        self.check(2, 'protocol_mismatch')
        self.check(None, 'busy')

    def test_closed_port(self):
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertEqual(endpoint.handshake(port, 69, timeout=0.3), 'closed')

    def test_connect_timeout_is_closed_not_busy(self):
        # Windows 未监听端口表现为连接超时，不能误报为已有分析器
        with patch.object(endpoint.socket, 'create_connection', side_effect=socket.timeout()):
            self.assertEqual(endpoint.handshake(8086, 69, timeout=0.3), 'closed')

    def test_resolve_reports_mismatch_and_busy_without_trying_other_versions(self):
        for state, code in (('protocol_mismatch', 'protocol_mismatch'), ('busy', 'profiler_busy'), ('closed', 'profiler_unavailable')):
            with patch.object(endpoint, 'handshake', return_value=state) as handshake:
                with self.assertRaises(EngineError) as raised:
                    endpoint.resolve(Path('.'), 69, port=8086)
            self.assertEqual(raised.exception.code, code)
            handshake.assert_called_once_with(8086, 69)

    def test_auto_discovery_requires_single_target(self):
        with patch.object(endpoint, 'discover', return_value=[]):
            with self.assertRaises(EngineError) as raised:
                endpoint.resolve(Path('.'), 69)
            self.assertEqual(raised.exception.code, 'profiler_unavailable')
        two = [{'pid': 1, 'port': 8086}, {'pid': 2, 'port': 8087}]
        with patch.object(endpoint, 'discover', return_value=two):
            with self.assertRaises(EngineError) as raised:
                endpoint.resolve(Path('.'), 69)
            self.assertEqual(raised.exception.code, 'ambiguous_target')
        with patch.object(endpoint, 'discover', return_value=two[:1]), \
                patch.object(endpoint, 'handshake', return_value='welcome'):
            self.assertEqual(endpoint.resolve(Path('.'), 69)['port'], 8086)


def raw_report():
    def zone(name, file, line, count, total, self_ns, max_ns, threads=((1, None),)):
        return {'name': name, 'function': name, 'file': file, 'line': line, 'count': count, 'total_ns': total,
                'self_ns': self_ns, 'max_ns': max_ns, 'min_ns': 1, 'p50_ns': total // count, 'p90_ns': max_ns,
                'p95_ns': max_ns, 'p99_ns': max_ns, 'threads': [{'id': t, 'self_ns': s or self_ns} for t, s in threads]}
    deployed = '/x/instances/i/data/games/com.netease/behavior_packs/dev_abc/Demo/server/system.py'
    zones = [
        zone('Main Update', 'E:\\src\\MinecraftGame.cpp', 5798, 100, 2_000_000_000, 100_000_000, 80_000_000),
        zone('Update', deployed, 20, 100, 400_000_000, 1_000_000, 40_000_000),
        zone('slow_path', deployed, 30, 100, 399_000_000, 300_000_000, 39_000_000),
        zone('time', 'time', 0, 1000, 99_000_000, 99_000_000, 1_000_000),
        zone('serverUpdate', 'Engine', 0, 200, 600_000_000, 200_000_000, 60_000_000),
    ]
    edges = [{'parent': -1, 'child': 0, 'count': 100, 'total_ns': 2_000_000_000},
             {'parent': 0, 'child': 1, 'count': 100, 'total_ns': 400_000_000},
             {'parent': 1, 'child': 2, 'count': 100, 'total_ns': 399_000_000},
             {'parent': 2, 'child': 3, 'count': 1000, 'total_ns': 99_000_000}]
    return {'schema': 1, 'tracy_version': '0.11.1',
            'capture': {'name': 'c', 'program': 'mcpelauncher-client', 'span_ns': 10_000_000_000, 'zone_count': 1500},
            'frame_marks': {}, 'threads': [{'id': 1, 'name': 'Main thread', 'self_ns': 1}, {'id': 2, 'name': 'Idle', 'self_ns': 1}],
            'zones': zones, 'edges': edges,
            'windows': [{'zone': 'Main Update', 'slowest': [{'start_ns': 1_000_000_000, 'duration_ns': 80_000_000, 'thread': 1,
                                                             'top_self': [{'zone': 3, 'thread': 2, 'self_ns': 70_000_000},
                                                                          {'zone': 2, 'thread': 1, 'self_ns': 30_000_000}]}]}]}


class AnalysisTests(unittest.TestCase):
    def test_classify_and_module_path(self):
        self.assertEqual(analysis.classify({'file': 'a/b.py', 'line': 3}), 'script')
        self.assertEqual(analysis.classify({'file': 'time', 'line': 0}), 'builtin')
        self.assertEqual(analysis.classify({'file': 'Engine', 'line': 0}), 'engine')
        self.assertEqual(analysis.classify({'file': 'E:\\x\\a.cpp', 'line': 9}), 'engine')
        self.assertEqual(analysis.module_path('/d/behavior_packs/dev_1/Mod/a.py'), 'Mod/a.py')
        self.assertEqual(analysis.module_path('C:\\MCStudio\\behavior_packs\\pack\\Mod\\a.py'), 'Mod/a.py')
        self.assertEqual(analysis.module_path('D:\\proj\\behavior_pack\\Mod\\a.py'), 'Mod/a.py')
        self.assertIsNone(analysis.module_path('mod/common/system/baseSystem.py'))

    def test_summary_maps_sources_and_attributes_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / 'behavior_pack' / 'Demo' / 'server' / 'system.py'
            source.parent.mkdir(parents=True)
            source.write_text('')
            summary = analysis.summarize(raw_report(), project, top=5)
        self.assertEqual(summary['main_loop']['p50_ms'], 20.0)
        self.assertEqual(summary['server_tick']['per_second'], 20.0)
        first = summary['scripts'][0]
        self.assertEqual((first['name'], first['source'], first['line']), ('Update', str(Path('behavior_pack/Demo/server/system.py')), 20))
        slow = next(s for s in summary['scripts'] if s['name'] == 'slow_path')
        self.assertEqual(slow['callers'], ['Update (Demo/server/system.py:20)'])
        self.assertEqual(summary['script']['builtin_from_script_ms_per_s'], 9.9)
        self.assertEqual(summary['script']['self_ms_per_s'], 30.1)
        window = summary['windows'][0]['slowest'][0]
        self.assertEqual([e['thread'] for e in window['top_self']], ['Main thread', 'Idle'], '窗口所在线程优先')
        text = analysis.format_summary(summary)
        self.assertIn('slow_path', text)
        self.assertIn('最慢的 Main Update', text)

    def test_main_loop_follows_engine_version_naming(self):
        raw = raw_report()
        raw['zones'][0]['name'] = 'Main app outer update'  # 3.10 的主循环区段名
        raw['windows'] = [dict(raw['windows'][0], zone='Main app outer update'),
                          {'zone': 'Main Update', 'slowest': []}, {'zone': 'update', 'slowest': []}]
        summary = analysis.summarize(raw, None)
        self.assertEqual(summary['main_loop']['zone'], 'Main app outer update')
        self.assertEqual([w['zone'] for w in summary['windows']], ['Main app outer update'])
        raw['zones'][0].update(name='update', file='Engine', line=0)  # 只有通用 update 时回退
        self.assertEqual(analysis.summarize(raw, None)['main_loop']['zone'], 'update')

    def test_filter_limits_script_list(self):
        summary = analysis.summarize(raw_report(), None, filter='slow')
        self.assertEqual([s['name'] for s in summary['scripts']], ['slow_path'])

    def test_diff_normalizes_by_capture_length(self):
        before = analysis.summarize(raw_report(), None, top=50)
        raw = raw_report()
        raw['capture']['span_ns'] *= 2  # 同样耗时、两倍时长 → 每秒耗时减半
        after = analysis.summarize(raw, None, top=50)
        result = analysis.diff(before, after, top=3)
        update = next(r for r in result['scripts'] if r['name'] == 'Update')
        self.assertEqual((update['base_ms_per_s'], update['new_ms_per_s'], update['delta_ms_per_s']), (40.0, 20.0, -20.0))
        self.assertIn('Update', analysis.format_diff(result))

    def test_load_caches_by_tool_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / 'a.tracy'
            trace.write_bytes(b'x')
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                return type('Done', (), {'returncode': 0, 'stdout': json.dumps(raw_report()).encode(), 'stderr': b''})()
            with patch.object(tools, 'require', return_value=Path('report')), \
                    patch.object(tools, 'installed_identity', return_value='one'), \
                    patch.object(analysis.subprocess, 'run', side_effect=run):
                analysis.load(trace)
                analysis.load(trace)
                self.assertEqual(len(calls), 1)
                for name in analysis.WINDOWS:
                    self.assertIn(name, calls[0])
                self.assertEqual(calls[0][-1], str(trace.resolve()))
                with patch.object(tools, 'installed_identity', return_value='two'):
                    analysis.load(trace)
                self.assertEqual(len(calls), 2)


class CliTests(unittest.TestCase):
    def test_report_json_and_human_output(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / 'a.tracy'
            trace.write_bytes(b'x')
            with patch.object(analysis, 'load', return_value=raw_report()):
                result = CliRunner().invoke(cli, ['--project', temp, 'profile', 'report', str(trace), '--json'])
                data = json.loads(result.output)
                self.assertTrue(data['ok'], result.output)
                self.assertEqual(data['scripts'][0]['name'], 'Update')
                human = CliRunner().invoke(cli, ['--project', temp, 'profile', 'report', str(trace)])
                self.assertIn('脚本函数（按总耗时）', human.output)

    def test_open_rejects_target_with_trace_file(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / 'a.tracy'
            trace.write_bytes(b'x')
            with patch.object(tools, 'require', return_value=Path('tracy-profiler')):
                result = CliRunner().invoke(cli, ['profile', 'open', str(trace), '--port', '8086', '--json'])
            self.assertFalse(json.loads(result.output)['ok'])

    def test_open_live_launches_profiler_against_resolved_port(self):
        launched = []
        with patch.object(tools, 'require', return_value=Path('tracy-profiler')), \
                patch.object(endpoint, 'resolve', return_value={'port': 8087, 'protocol': 69}), \
                patch('mcpywrap_core.commands.profile_cmd._launch', side_effect=lambda c: launched.append(c) or 42):
            result = CliRunner().invoke(cli, ['profile', 'open', '--port', '8087', '--json'])
        data = json.loads(result.output)
        self.assertTrue(data['ok'], result.output)
        self.assertEqual(launched, [['tracy-profiler', '-a', '127.0.0.1', '-p', '8087']])


if __name__ == '__main__':
    unittest.main()
