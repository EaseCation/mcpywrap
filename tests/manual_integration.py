"""可复现的本机验收：真实 CLI/pip/watchdog，--game 时启动已安装的 MCS 引擎。

在独立、带 system-site-packages 的虚拟环境中执行，避免安装到用户工具环境。
所有测试项目和日志保留在 --workspace；只移除本次新建的全局链接。
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid
from unittest.mock import patch

from mcpywrap.dependencies import DependencyService, read_project, write_project
from mcpywrap.builders.project_builder import AddonProjectBuilder
from mcpywrap.builders.watcher import ProjectWatcher
from mcpywrap.mcstudio.mcs import get_mcs_game_engine_netease_data_path, get_mcs_game_engine_data_path


def snapshot(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


def make_addon(path, identity, configured=False, local=(), resource_only=False):
    path.mkdir(parents=True)
    kinds = [('resource', 'resources')] if resource_only else [('behavior', 'data'), ('resource', 'resources')]
    for kind, module in kinds:
        folder = path / (kind + '_pack')
        folder.mkdir()
        manifest = {'format_version': 1,
                    'header': {'name': 'McpyTest_' + identity, 'description': 'Local dependency acceptance',
                               'uuid': str(uuid.uuid4()), 'version': [1, 0, 0]},
                    'modules': [{'type': module, 'uuid': str(uuid.uuid4()), 'version': [1, 0, 0]}]}
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (folder / ('evidence_' + identity + '.txt')).write_text(identity, encoding='utf-8')
    if not resource_only:
        scripts = path / 'behavior_pack' / ('mcpytest_' + identity)
        scripts.mkdir()
        (scripts / '__init__.py').write_text('', encoding='utf-8')
        (scripts / 'modMain.py').write_text('''# -*- coding: utf-8 -*-
from mod.common.mod import Mod
@Mod.Binding(name="McpyTest_%s", version="1.0")
class AcceptanceMod(object):
    @Mod.InitServer()
    def serverInit(self):
        print("MCPY_ACCEPT_SERVER_%s")
    @Mod.InitClient()
    def clientInit(self):
        print("MCPY_ACCEPT_CLIENT_%s")
''' % (identity, identity, identity), encoding='utf-8')
        (path / 'behavior_pack' / 'precedence.txt').write_text(identity, encoding='utf-8')
    texts = path / 'resource_pack' / 'texts'
    texts.mkdir()
    (texts / 'en_US.lang').write_text('mcpy.priority=' + identity + '\nmcpy.' + identity + '=present\n', encoding='utf-8')
    if configured:
        write_project(path, {'project': {'name': 'mcpy-test-' + identity, 'version': '1.0.0', 'dependencies': []},
                             'tool': {'mcpywrap': {'project_type': 'addon', 'target_dir': './build',
                                                  'local_dependencies': list(local)}}})
    return path


def cli(path, *args, expected=0):
    result = subprocess.run([sys.executable, '-m', 'mcpywrap', *args], cwd=path,
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    with (path.parent / 'cli.log').open('a', encoding='utf-8') as output:
        output.write(f'\n{path}: mcpy {args}\nexit={result.returncode}\n{result.stdout}\n{result.stderr}')
    assert result.returncode == expected, result.stdout + result.stderr
    return result


def wait_for(predicate, timeout=12):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            if predicate():
                return
        except (FileNotFoundError, PermissionError):
            pass
        time.sleep(0.1)
    raise AssertionError('Timed out waiting for real filesystem watcher')


def launch(project, evidence, expected, timeout):
    """仅替换日志窗口为文件收集器；游戏、配置生成、链接均走真实实现。"""
    import psutil
    assert not any(p.info['name'] == 'Minecraft.Windows.exe' for p in psutil.process_iter(['name'])), '请先结束现有游戏后再运行本机测试'
    run = importlib.import_module('mcpywrap.commands.run_cmd')
    evidence_name = project.parent.name + '-assembled' if project.name == 'build' else project.name
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen()
    server.settimeout(0.5)
    port = server.getsockname()[1]
    stopped = threading.Event()
    chunks, clients = [], []

    def receive(client):
        client.settimeout(0.5)
        while not stopped.is_set():
            try:
                data = client.recv(65536)
                if not data:
                    break
                chunks.append(data)
            except socket.timeout:
                continue
            except OSError:
                break

    def accept():
        while not stopped.is_set():
            try:
                client, _ = server.accept()
                clients.append(client)
                threading.Thread(target=receive, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    threading.Thread(target=accept, daemon=True).start()
    global_root = Path(get_mcs_game_engine_netease_data_path())
    packs = run._setup_dependencies(project.name, str(project))
    planned = [global_root / (kind + '_packs') / (Path(folder).name + '_' + pack.pkg_name)
               for pack in packs for kind in ('behavior', 'resource')
               if (folder := getattr(pack, kind + '_pack_dir')) and Path(folder).is_dir()]
    created = [p for p in planned if not os.path.lexists(p)]
    level, config = run._generate_new_instance_config(str(project), project.name)
    proc = None
    try:
        with patch.object(run, '_gen_random_port', return_value=port), patch(
                'mcpywrap.mcstudio.studio_server_ui.run_studio_server_ui_subprocess', return_value=None):
            success, proc = run._run_game_with_instance(config, level, packs, wait=False)
        assert success and proc, 'Actual game launch failed'
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and proc.poll() is None:
            log = b''.join(chunks).decode('utf-8', errors='replace')
            if all('MCPY_ACCEPT_' + side + '_' + name in log for side in ('SERVER', 'CLIENT') for name in expected):
                break
            time.sleep(0.5)
        log = b''.join(chunks).decode('utf-8', errors='replace')
        (evidence / (evidence_name + '-game.log')).write_text(log, encoding='utf-8')
        loaded = [side + '_' + name for side in ('SERVER', 'CLIENT') for name in expected
                  if 'MCPY_ACCEPT_' + side + '_' + name in log]
        world = Path(get_mcs_game_engine_data_path()) / 'minecraftWorlds' / level
        registered = {}
        for kind in ('behavior', 'resource'):
            declared = {json.loads((Path(folder) / 'manifest.json').read_text())['header']['uuid']
                        for pack in packs if (folder := getattr(pack, kind + '_pack_dir')) and Path(folder).is_dir()}
            world_file = world / ('netease_world_' + kind + '_packs.json')
            actual = {entry['pack_id'] for entry in json.loads(world_file.read_text())} if world_file.exists() else set()
            registered[kind] = {'expected': sorted(declared), 'actual': sorted(actual), 'passed': declared == actual}
            if world_file.exists():
                (evidence / (evidence_name + '-' + kind + '-packs.json')).write_bytes(world_file.read_bytes())
        return {'pid': proc.pid, 'exit_code_before_cleanup': proc.poll(), 'config': config,
                'expected_markers': 2 * len(expected), 'loaded_markers': loaded,
                'registered_packs': registered,
                'passed': len(loaded) == 2 * len(expected) and all(v['passed'] for v in registered.values()), 'log_bytes': len(log)}
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=20)
        stopped.set()
        server.close()
        for client in clients:
            client.close()
        for link in created:
            if link.is_symlink():
                link.unlink()
            elif link.is_junction():
                os.rmdir(link)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--game', action='store_true')
    parser.add_argument('--timeout', type=int, default=90)
    args = parser.parse_args()
    root = args.workspace.resolve()
    root.mkdir(parents=True, exist_ok=False)
    report = {'workspace': str(root), 'checks': [], 'games': {}}
    leaf = make_addon(root / '中文 common', 'leaf')
    before = snapshot(leaf)
    a = make_addon(root / 'a' / 'shared', 'a', True, ['../../中文 common'])
    b = make_addon(root / 'b' / 'shared', 'b', True, ['../../中文 common'])
    resources = make_addon(root / 'resources only', 'resources', resource_only=True)
    local = make_addon(root / 'local-main', 'localmain', True)
    mixed = make_addon(root / 'mixed-main', 'mixedmain', True)
    package = make_addon(root / 'python-package', 'package', True, ['../中文 common'])
    config = read_project(package)
    config['build-system'] = {'requires': ['setuptools'], 'build-backend': 'setuptools.build_meta'}
    config['tool']['setuptools'] = {'packages': []}
    write_project(package, config)
    installed = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--no-build-isolation', '-e', str(package)],
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
    (root / 'pip.log').write_text(installed.stdout + installed.stderr, encoding='utf-8')
    assert installed.returncode == 0, installed.stderr
    cli(local, 'add', '--path', '../a/shared')
    cli(local, 'add', '--path', str(b))
    cli(local, 'add', '--path', '../resources only')
    cli(local, 'add', '--path', '../中文 common')
    cli(local, 'add', '--path', str(leaf))  # equivalent declaration dedup
    cli(local, 'build')
    assert len(DependencyService(local).list()) == 4
    assert len(DependencyService(local).resolve().dependency_map) == 4
    assert (local / 'build/behavior_pack/precedence.txt').read_text() == 'localmain'
    assert len(list((local / 'build/behavior_pack').glob('mcpytest_*'))) == 4
    report['checks'].append('real CLI: local-only diamond, same names, relative/absolute, Chinese/spaces, resource-only, duplicate, main priority')
    cli(mixed, 'add', 'mcpy-test-package>=1.0')
    cli(mixed, 'add', '--path', '../b/shared')
    cli(mixed, 'build')
    assert [Path(p.path) for p in DependencyService(mixed).resolve().dependency_map.values()] == [leaf, package, b]
    report['checks'].append('real pip editable package + local graph and version constraints')
    watcher = ProjectWatcher(str(local), str(local / 'build'))
    watcher.setup_from_config('localmain')
    watcher.start()
    try:
        own = local / 'behavior_pack/precedence.txt'
        own.unlink()
        wait_for(lambda: (local / 'build/behavior_pack/precedence.txt').read_text() == 'b')
        transient = b / 'behavior_pack/new-directory'
        transient.mkdir()
        (transient / 'new.txt').write_text('watch-added')
        wait_for(lambda: (local / 'build/behavior_pack/new-directory/new.txt').read_text() == 'watch-added')
        (transient / 'new.txt').rename(transient / 'renamed.txt')
        wait_for(lambda: (local / 'build/behavior_pack/new-directory/renamed.txt').exists() and not (local / 'build/behavior_pack/new-directory/new.txt').exists())
        (transient / 'renamed.txt').unlink()
        transient.rmdir()
        wait_for(lambda: not (local / 'build/behavior_pack/new-directory/renamed.txt').exists())
    finally:
        watcher.stop()
    incremental = snapshot(local / 'build')
    cli(local, 'build')
    assert incremental == snapshot(local / 'build')
    report['checks'].append('real watchdog: deletion fallback, directory create, move, delete; identical hashes to full build')
    cycle = make_addon(root / 'cycle', 'cycle', True, ['../local-main'])
    config_before = (local / 'pyproject.toml').read_bytes()
    cli(local, 'add', '--path', str(cycle), expected=1)
    assert (local / 'pyproject.toml').read_bytes() == config_before
    config = read_project(local)
    config['tool']['mcpywrap']['local_dependencies'].append('../missing')
    write_project(local, config)
    output_before = snapshot(local / 'build')
    cli(local, 'build', expected=1)
    cli(local, 'remove', '--path', '../missing')
    assert snapshot(local / 'build') == output_before
    assert snapshot(leaf) == before
    report['checks'].append('cycle rollback, invalid graph preserves output, missing source removable, raw dependency unchanged')
    if args.game:
        for project, expected in [(local, ['leaf', 'a', 'b', 'localmain']), (mixed, ['leaf', 'package', 'b', 'mixedmain'])]:
            report['games'][project.name] = launch(project, root, expected, args.timeout)
            (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            # 产物独立运行，不声明任何源依赖，验证确实完成内容组装。
            built = project / 'build'
            write_project(built, {'project': {'name': project.name + '-assembled'},
                                  'tool': {'mcpywrap': {'project_type': 'addon'}}})
            result = launch(built, root, expected, args.timeout)
            report['games'][project.name + '-assembled'] = result
            (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        assert snapshot(leaf) == before, 'Game changed raw dependency files'
    (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if any(not game['passed'] for game in report['games'].values()):
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
