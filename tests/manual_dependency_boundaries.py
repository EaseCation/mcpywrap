"""本机验收：构建并检查 ZIP；--game 显式启动开发项目及解包产物验证日志。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

from manual_integration import make_addon, snapshot
from mcpywrap.dependencies import read_project, write_project


def remove_test_links(workspace):
    """只清理指向本次临时项目的链接，让解包验收不借用开发源码。"""
    from mcpywrap.mcstudio.mcs import get_mcs_game_engine_netease_data_path
    base = Path(get_mcs_game_engine_netease_data_path())
    for kind in ('behavior', 'resource'):
        folder = base / (kind + '_packs')
        for link in folder.iterdir() if folder.is_dir() else ():
            is_junction = getattr(link, 'is_junction', lambda: False)()
            if not (link.is_symlink() or is_junction):
                continue
            try:
                link.resolve().relative_to(workspace.resolve())
            except ValueError:
                continue
            if is_junction:
                os.rmdir(link)
            else:
                link.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--game', action='store_true')
    args = parser.parse_args()
    root = args.workspace.resolve()
    root.mkdir(parents=True, exist_ok=False)

    def call(project, *command):
        proc = subprocess.run([sys.executable, '-m', 'mcpywrap', '--local', '--project', str(project),
                               '--non-interactive', *command, '--json'], capture_output=True,
                              text=True, encoding='utf-8', errors='replace',
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        with (root / 'cli.log').open('a', encoding='utf-8') as log:
            log.write(f'{project}: {command}\n{proc.stdout}\n{proc.stderr}\n')
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return json.loads(proc.stdout)

    shared = make_addon(root / 'shared', 'shared')
    project = make_addon(root / 'project', 'main', configured=True)
    utils = shared / 'behavior_pack/mcpytest_shared/utils.py'
    utils.write_text('def message():\n    return "SHARED_PURE_PYTHON_OK"\n', encoding='utf-8')
    mod = project / 'behavior_pack/mcpytest_main/modMain.py'
    script = mod.read_text(encoding='utf-8')
    script = script.replace('from mod.common.mod import Mod',
                            'from mod.common.mod import Mod\nfrom mcpytest_shared.utils import message')
    script = script.replace('print("MCPY_ACCEPT_SERVER_main")', 'print("MCPY_ACCEPT_SERVER_main")\n        print("SERVER_" + message())')
    script = script.replace('print("MCPY_ACCEPT_CLIENT_main")', 'print("MCPY_ACCEPT_CLIENT_main")\n        print("CLIENT_" + message())')
    mod.write_text(script, encoding='utf-8')
    # 复用工具已有的纯 Python/原生开发包，不修改工具安装环境。
    config = read_project(project)
    config['project']['dependencies'] = ['click>=8', 'psutil>=5.8']
    write_project(project, config)
    before = snapshot(shared)
    added = call(project, 'add', '--path', '../shared')
    assert len(added['warnings']) == 2
    call(project, 'build')
    packaged = call(project, 'package')
    assert len(packaged['warnings']) == 2
    unpacked = root / 'unpacked'
    unpacked.mkdir()
    with zipfile.ZipFile(packaged['artifact']) as archive:
        names = archive.namelist()
        assert any(name.endswith('mcpytest_shared/utils.py') for name in names)
        assert any(name.endswith('mcpytest_main/modMain.py') for name in names)
        assert not any('site-packages' in name or 'click/' in name or 'psutil/' in name for name in names)
        archive.extractall(unpacked)
    for kind, suffix in [('behavior', 'bp'), ('resource', 'rp')]:
        (unpacked / ('mcpy-test-main_' + suffix)).rename(unpacked / (kind + '_pack'))
    call(unpacked, 'init', '--name', 'unpacked', '--type', 'addon')
    assert snapshot(shared) == before
    report = {'artifact': packaged['artifact'], 'warnings': packaged['warnings'],
              'zip_entries': names, 'shared_unchanged': True, 'games': []}
    try:
        if args.game:
            import psutil
            assert not any(p.info['name'] == 'Minecraft.Windows.exe' for p in psutil.process_iter(['name'])), '已有游戏正在运行，请先自行结束后再验收'
            expected = ['MCPY_ACCEPT_' + side + '_' + name for side in ('SERVER', 'CLIENT') for name in ('main', 'shared')]
            expected += [side + '_SHARED_PURE_PYTHON_OK' for side in ('SERVER', 'CLIENT')]
            for source in (project, unpacked):
                started = call(source, 'run', '--new', '--no-gui', '--detach')
                entry = {'project': str(source), 'session': started['session'], 'pid': started['pid'],
                         'log_path': started['log_path'], 'loaded': [], 'passed': False}
                report['games'].append(entry)
                try:
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        text = Path(started['log_path']).read_text(encoding='utf-8', errors='replace')
                        entry['loaded'] = [marker for marker in expected if marker in text]
                        if len(entry['loaded']) == len(expected):
                            entry['passed'] = True
                            break
                        time.sleep(0.5)
                    assert entry['passed'], f'缺少游戏加载标记: {entry}'
                finally:
                    call(source, 'stop', '--session', started['session'])
                    remove_test_links(root)
    finally:
        (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
