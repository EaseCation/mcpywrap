"""AArch64 Linux 原生后端：宿主识别、运行包布局、安装校验、显示诊断与启动命令。"""
import hashlib
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from mcpywrap_core.engines import host as host_module
from mcpywrap_core.engines import install as installer
from mcpywrap_core.engines import platforms
from mcpywrap_core.engines.backend import get_backend
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.engines.linux import LinuxBackend, display_diagnostics
from mcpywrap_core.engines.platforms import LINUX, MACOS

ELF_AARCH64 = b'\x7fELF\x02\x01\x01' + b'\x00' * 11 + struct.pack('<H', 183) + b'\x00' * 44
ELF_X86_64 = b'\x7fELF\x02\x01\x01' + b'\x00' * 11 + struct.pack('<H', 62) + b'\x00' * 44
LINUX_HOST = {'backend': 'linux-arm64', 'platform': 'linux', 'architecture': 'aarch64',
              'glibc_version': '2.41', 'macos_version': None}


class HostDetectionTests(unittest.TestCase):
    def describe(self, system, machine, libc=('glibc', '2.41')):
        with patch.object(host_module.sys, 'platform', system), patch('platform.machine', return_value=machine), \
                patch('platform.libc_ver', return_value=libc):
            return host_module.describe()

    def test_glibc_aarch64_selects_linux_backend(self):
        result = self.describe('linux', 'aarch64')
        self.assertEqual((result['backend'], result['glibc_version']), ('linux-arm64', '2.41'))

    def test_other_linux_hosts_are_not_native(self):
        self.assertIsNone(self.describe('linux', 'x86_64')['backend'])
        self.assertIsNone(self.describe('linux', 'aarch64', ('', ''))['backend'])  # musl 等

    def test_backend_selection_and_capabilities(self):
        backend = get_backend('linux-arm64')
        self.assertIsInstance(backend, LinuxBackend)
        self.assertEqual(backend.id, 'linux-arm64')
        self.assertIn('linux-local-worlds', backend.capabilities)
        self.assertIn('network-sessions', backend.capabilities)
        self.assertNotIn('macos-local-worlds', backend.capabilities)

    def test_project_ui_requires_optional_qt(self):
        with patch('importlib.util.find_spec', return_value=None):
            self.assertNotIn('project-ui', LinuxBackend().capabilities)
        with patch('importlib.util.find_spec', return_value=object()):
            self.assertIn('project-ui', LinuxBackend().capabilities)

    def test_require_native_rejects_mismatched_host(self):
        with patch.object(host_module, 'describe', return_value=dict(LINUX_HOST, backend='macos-arm64')):
            with self.assertRaises(EngineError) as caught:
                host_module.require_native(LINUX)
        self.assertEqual(caught.exception.code, 'unsupported_platform')


class PlatformLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_executable_formats_are_platform_specific(self):
        elf, mach, other = self.root/'elf', self.root/'mach', self.root/'x86'
        elf.write_bytes(ELF_AARCH64); other.write_bytes(ELF_X86_64)
        mach.write_bytes(struct.pack('<II', 0xfeedfacf, 0x100000c))
        self.assertTrue(LINUX.native_executable(elf))
        self.assertFalse(LINUX.native_executable(other))
        self.assertFalse(LINUX.native_executable(mach))
        self.assertTrue(MACOS.native_executable(mach))
        self.assertFalse(MACOS.native_executable(elf))

    def test_layout_paths_and_metadata_lookup(self):
        app = self.root/'McpyRuntime'
        self.assertEqual(LINUX.client(app), app/'bin/mcpelauncher-client')
        self.assertEqual(LINUX.launcher(app), app/'resources/launcher')
        self.assertEqual(LINUX.instances_root(self.root), self.root/'.runtime/linux/instances')
        (app/'resources').mkdir(parents=True); (app/'resources/runtime.json').write_text('{}')
        self.assertEqual(platforms.metadata_path(app), app/'resources/runtime.json')
        self.assertEqual(installer.platform_of_runtime(app), LINUX)
        self.assertEqual(installer.platform_of_runtime(self.root/'McpyRuntime.app'), MACOS)

    def test_default_home_follows_xdg(self):
        with patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root/'xdg')}, clear=False):
            self.assertEqual(platforms.default_home('linux'), self.root/'xdg/mcpy')
        self.assertEqual(platforms.default_home('darwin'), Path('~/Library/Application Support/mcpy').expanduser())


class DisplayDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)

    def test_wayland_socket_is_detected(self):
        (self.runtime/'wayland-0').touch()
        result = display_diagnostics({'WAYLAND_DISPLAY': 'wayland-0', 'XDG_RUNTIME_DIR': str(self.runtime)})
        self.assertTrue(result['ok']); self.assertEqual(result['session'], 'wayland')

    def test_missing_session_has_actionable_hint(self):
        result = display_diagnostics({})
        self.assertFalse(result['ok']); self.assertIn('WAYLAND_DISPLAY', result['hint'])
        stale = display_diagnostics({'WAYLAND_DISPLAY': 'wayland-9', 'XDG_RUNTIME_DIR': str(self.runtime)})
        self.assertFalse(stale['ok']); self.assertIn('不存在', stale['error'])

    def test_remote_x11_display_is_not_probed(self):
        self.assertEqual(display_diagnostics({'DISPLAY': 'workstation:0'})['session'], 'x11')

    def test_missing_render_node_is_a_warning(self):
        with patch('mcpywrap_core.engines.linux.render_nodes', return_value=[]):
            result = display_diagnostics({'DISPLAY': 'workstation:0'})
        self.assertTrue(result['ok']); self.assertFalse(result['gpu']); self.assertIn('render', result['warning'])


class LinuxInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'MCPY_ENGINE_HOME': str(self.root/'home'), 'MCPY_RUNTIME_CATALOG': ''})
        env.start(); self.addCleanup(env.stop)
        for name in ('describe', 'require_native'):
            mock = patch.object(installer, name, return_value=LINUX_HOST); mock.start(); self.addCleanup(mock.stop)
        display = patch('mcpywrap_core.engines.linux.display_diagnostics',
                        return_value={'ok': True, 'session': 'wayland', 'gpu': True, 'render_nodes': []})
        display.start(); self.addCleanup(display.stop)
        self.codesign = patch.object(installer.subprocess, 'run', side_effect=AssertionError('codesign on Linux'))
        self.codesign.start(); self.addCleanup(self.codesign.stop)
        self.apk = self.root/'dev_launcher_3.10.apk'
        with zipfile.ZipFile(self.apk, 'w') as archive:
            archive.writestr('AndroidManifest.xml', b'fixture')
            archive.writestr('assets/data.bin', b'data')
        self.profile = {'id': 'fixture', 'package_name': 'com.netease.mctest',
                        'apk': {'version': '3.10', 'filename': self.apk.name, 'size': self.apk.stat().st_size,
                                'sha256': installer.digest(self.apk)}, 'unpacked_size': 11, 'file_count': 2,
                        'files': {'AndroidManifest.xml': hashlib.sha256(b'fixture').hexdigest()}}
        app = self.root/'McpyRuntime'
        exe = app/'bin/mcpelauncher-client'; exe.parent.mkdir(parents=True)
        exe.write_bytes(ELF_AARCH64); exe.chmod(0o755)
        meta = app/'resources/runtime.json'; meta.parent.mkdir()
        meta.write_text(json.dumps({'platform': 'linux-arm64', 'minimum_glibc': '2.35', 'launch_protocol': 1,
                                    'client_python_protocol': 1, 'cppconfig_protocol': 1, 'game_profile': self.profile}))
        self.exe, self.meta = exe, meta
        integrity = self.root/'McpyRuntime.integrity.json'
        integrity.write_text(json.dumps({'files': {p.relative_to(app).as_posix(): installer.digest(p) for p in (exe, meta)}}))
        self.archive = self.root/'runtime.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive:
            archive.add(app, arcname=app.name)
            archive.add(integrity, arcname=integrity.name)
        self.cat = {'schema': 1, 'runtime': {'id': 'linux-arm64-fixture', 'platform': 'linux-arm64',
                    'minimum_glibc': '2.35', 'archive_root': 'McpyRuntime', 'url': self.archive.name,
                    'size': self.archive.stat().st_size, 'sha256': installer.digest(self.archive)},
                    'profile': self.profile}
        self.catalog = self.root/'catalog-linux-arm64.json'; self.catalog.write_text(json.dumps(self.cat))

    def test_catalog_must_match_platform(self):
        installer.validate_catalog(self.cat, LINUX)
        with self.assertRaises(EngineError):
            installer.validate_catalog(self.cat, MACOS)
        darwin = json.loads(json.dumps(self.cat)); darwin['runtime'].update(platform='darwin-arm64', archive_root='McpyRuntime.app')
        with self.assertRaises(EngineError):
            installer.validate_catalog(darwin, LINUX)
        missing = json.loads(json.dumps(self.cat)); del missing['runtime']['minimum_glibc']
        with self.assertRaises(EngineError):
            installer.validate_catalog(missing, LINUX)

    def test_default_catalog_is_platform_specific(self):
        self.assertIn('linux-arm64', installer.DEFAULT_CATALOGS['linux-arm64'])
        self.assertEqual(installer.DEFAULT_CATALOGS['macos-arm64'], installer.DEFAULT_CATALOG)

    def test_install_verifies_elf_runtime_without_codesign(self):
        result = installer.install(str(self.catalog), str(self.apk), target=LINUX)
        self.assertTrue(result['ok'], result)
        self.assertEqual(Path(result['runtime']).name, 'McpyRuntime')
        self.assertEqual(result['minimum_glibc'], '2.35')
        self.assertTrue(installer.diagnose(check_files=True, target=LINUX)['ok'])
        self.assertFalse((Path(result['game']).parent/'icons').exists())

    def test_old_glibc_is_rejected_before_installing(self):
        old = dict(LINUX_HOST, glibc_version='2.31')
        with patch.object(installer, 'require_native', return_value=old):
            with self.assertRaises(EngineError) as caught:
                installer.install(str(self.catalog), str(self.apk), target=LINUX)
        self.assertEqual(caught.exception.code, 'os_too_old')
        self.assertFalse((installer.home()/'runtimes').exists())

    def test_non_native_executable_is_rejected(self):
        self.exe.write_bytes(ELF_X86_64)
        integrity = self.root/'McpyRuntime.integrity.json'
        app = self.root/'McpyRuntime'
        integrity.write_text(json.dumps({'files': {p.relative_to(app).as_posix(): installer.digest(p) for p in (self.exe, self.meta)}}))
        with self.assertRaises(EngineError) as caught:
            installer.verify_runtime(app, integrity, self.profile)
        self.assertEqual(caught.exception.code, 'runtime_incompatible')

    def test_missing_display_blocks_ready_state(self):
        installer.install(str(self.catalog), str(self.apk), target=LINUX)
        with patch('mcpywrap_core.engines.linux.display_diagnostics',
                   return_value={'ok': False, 'error': '没有可用的图形显示会话。', 'hint': 'set WAYLAND_DISPLAY'}):
            result = installer.diagnose(target=LINUX)
        self.assertFalse(result['ok'])
        self.assertEqual((result['state'], result['hint']), ('display_unavailable', 'set WAYLAND_DISPLAY'))


class LinuxLaunchTests(unittest.TestCase):
    def test_helper_command_has_no_macos_renderer_flags(self):
        from mcpywrap_core.engines import macos
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        app = Path(tmp.name)/'McpyRuntime'
        helper = app/'resources/launcher/run_netease_dev.py'; helper.parent.mkdir(parents=True); helper.write_text('')
        (app/'resources/runtime.json').write_text(json.dumps({'addon_link_protocol': 1}))
        data = {'backend': 'linux-arm64', 'engine_log_path': str(Path(tmp.name)/'engine.log'),
                'launch': {'runtime': str(app), 'game': '/game', 'data': '/data', 'cache': '/cache',
                           'cppconfig': '/world.cppconfig'}}
        process = Mock(); process.poll.return_value = None; process.pid = 7
        with patch.object(macos.subprocess, 'Popen', return_value=process) as popen, \
                patch('mcpywrap_core.mcstudio.processes.identity', return_value={'executable': '/x/mcpelauncher-client'}):
            self.assertIs(macos.launch_session(data), process)
        command = popen.call_args.args[0]
        self.assertEqual(command[1], str(helper))
        self.assertNotIn('--angle-backend', command)
        self.assertIn('--link-source-addons', command)
        self.assertIn('--debug-loopback', command)

    def test_profiling_platform_tag(self):
        from mcpywrap_core.profiling import tools
        with patch.object(tools.sys, 'platform', 'linux'), patch('platform.machine', return_value='aarch64'):
            self.assertEqual(tools.platform_tag(), 'linux-arm64')


class LinuxDeploymentTests(unittest.TestCase):
    """Linux 实例的组装目录与 macOS 一样走共享部署比对（含引擎自建空目录放行）。"""
    def setUp(self):
        from test_runtime_deployment import fixture
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.project = fixture(Path(tmp.name).resolve(), 'linux-addon')
        config = LINUX.instances_root(self.project)/'world'/'world.cppconfig'
        config.parent.mkdir(parents=True)
        self.data = {'backend': 'linux-arm64', 'config_path': str(config), 'session': 's'*32}
        self.target = config.parent/'assembled'

    def test_refresh_targets_instance_assembly_and_allows_engine_empty_directories(self):
        from mcpywrap_core.runtime import deployment
        first = deployment.refresh(self.project, self.data)
        self.assertEqual(Path(first.behavior_pack_dir).parent, self.target)
        record = deployment.storage.read(deployment.metadata_path(self.project, self.target))
        # 网易引擎启动时在开发行为包里补建的空 entities/ 不算外部改写。
        (self.target/'behavior_pack/entities').mkdir()
        with patch.object(deployment, '_replace_with_retry', side_effect=AssertionError('unexpected write')):
            deployment.refresh(self.project, self.data)
        self.assertEqual(deployment.storage.read(deployment.metadata_path(self.project, self.target))['id'],
                         record['id'])
        # 目录里一旦出现文件仍然拦截。
        (self.target/'behavior_pack/entities/zombie.json').write_text('{}')
        with self.assertRaises(EngineError) as error:
            deployment.refresh(self.project, self.data)
        self.assertEqual(error.exception.code, 'deployment_modified')
        self.assertIn('behavior_pack/entities/', error.exception.details['changes'])


if __name__ == '__main__':
    unittest.main()
