"""可选人工验收：公开 CLI 验证准备次数；仅 --game 会启动独立测试游戏。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='必须尚不存在；保存独立项目、世界及证据')
    parser.add_argument('--command', help='已安装 mcpy 的可执行路径；默认使用当前 Python 的源码 CLI')
    parser.add_argument('--game', action='store_true', help='显式启动当前平台的游戏，验证后停止本次会话')
    parser.add_argument('--clients', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    if args.clients == 2 and not args.game:
        parser.error('--clients 2 需要 --game')
    repository = Path(__file__).resolve().parents[2]
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(repository/'skills/mcpywrap/assets/consumer-prepare', root/'fixture')
    project = root/'fixture/game'
    entry = root/'fixture/framework/build_tools/prepare.py'
    # 为本次独立夹具记录实际执行事件，不改写公开示例。
    entry.write_text(entry.read_text(encoding='utf-8') + '''
if __name__ == '__main__':
    with (Path(os.environ['MCPY_PROJECT_ROOT'])/'.mcpy/prepare-events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'event': os.environ['MCPY_EVENT'], 'operation': os.environ['MCPY_OPERATION']})+'\\n')
''', encoding='utf-8')
    command = [args.command] if args.command else [sys.executable, '-m', 'mcpywrap']
    evidence, owned, groups = [], set(), set()
    report = {'ok': False, 'platform': sys.platform, 'project': str(project), 'game_requested': args.game,
              'clients': args.clients, 'verification': 'preparation_only', 'commands': evidence}

    def call(label, *arguments, expect=True):
        started = time.monotonic()
        proc = subprocess.run([*command, '--local', '--project', str(project), '--non-interactive',
                               *arguments, '--json'], cwd=repository, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding='utf-8', timeout=360,
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        (root/(label+'.stderr')).write_text(proc.stderr, encoding='utf-8')
        data = json.loads(proc.stdout)
        evidence.append({'label': label, 'exit_code': proc.returncode,
                         'duration': round(time.monotonic()-started, 3), 'result': data})
        if data.get('group'):
            groups.add(data['group'])
        if data.get('session'):
            owned.add(data['session'])
        for member in data.get('members', []):
            if member.get('session'):
                owned.add(member['session'])
        (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(label, proc.returncode, data.get('state', ''), flush=True)
        if expect and (proc.returncode or not data.get('ok')):
            raise RuntimeError(data.get('error') or proc.stderr)
        return data

    def count():
        path = project/'.mcpy/prepare-events.jsonl'
        return len(path.read_text(encoding='utf-8').splitlines()) if path.exists() else 0

    try:
        call('sync', 'sync')
        assert count() == 0, 'sync 执行了 provider'
        call('plan', 'script', 'list', '--effective')
        assert count() == 0, '查询执行了 provider'
        call('build', 'build')
        assert count() == 1, 'build 没有恰好执行一次'
        call('package', 'package')
        assert count() == 2, 'package 没有恰好执行一次'
        if args.game:
            started = call('start', 'run', '--new', '--no-gui', '--detach', '--clients', str(args.clients))
            assert count() == 3, '本地启动没有恰好执行一次'
            if args.clients == 1:
                reused = call('reuse', 'run', started['instance'], '--no-gui', '--detach')
                assert reused.get('already_running') and count() == 3, '复用会话重复执行了准备'
                restarted = call('restart', 'restart', '--session', started['session'])
                assert count() == 4, '重启没有恰好执行一次'
                call('stop-restarted', 'stop', '--session', restarted['session'])
                owned.discard(restarted['session'])
            else:
                report['connection_verified'] = started.get('connection_verified', False)
                guest = next(member for member in started['members'] if member['role'] == 'guest')
                call('stop-guest', 'stop', '--session', guest['session'])
                call('retry-guest', 'restart', '--session', guest['session'])
                assert count() == 3, '补齐客机重复执行了主机准备'
                restarted = call('restart-group', 'restart', '--group', started['group'])
                assert count() == 4, '重启整组没有恰好执行一次'
                call('stop-group', 'stop', '--group', restarted['group'])
                groups.discard(restarted['group'])
            report['verification'] = 'local_process_lifecycle_and_preparation'
        (project/'data/items.json').write_text('{"updated": 11}', encoding='utf-8')
        previous = count()
        call('changed-input', 'build')
        assert count() == previous+1
        assert json.loads((project/'build/behavior_pack/generated/catalog.json').read_text()) == {'updated': 11}
        if args.game:
            (project/'data/items.json').write_text('{"invalid": "not-an-integer"}', encoding='utf-8')
            previous = count()
            failed = call('failed-prepare', 'run', '--new', '--no-gui', '--detach', expect=False)
            assert not failed.get('ok') and count() == previous, '无效输入未阻止准备'
            state = call('failed-status', 'status', '--list')
            assert all(item.get('state') not in ('starting', 'running') for item in state['sessions']), '失败准备创建了活动游戏'
            report['failed_prepare_started_game'] = False
        report['ok'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        # 夹具是本脚本独占的新目录；只结束保存过的本次目标，保留世界和日志。
        cleanup_errors = []
        if args.game:
            try:
                found = call('cleanup-discovery', 'status', '--list', expect=False)
                owned.update(item['session'] for item in found.get('sessions', []) if item.get('session'))
                groups.update(item['group'] for item in found.get('groups', []) if item.get('group'))
            except Exception as exc:
                cleanup_errors.append(str(exc))
        for group in sorted(groups):
            try:
                result = call('cleanup-group-'+group[:8], 'stop', '--group', group, expect=False)
                if not result.get('ok'):
                    cleanup_errors.append(result.get('error'))
            except Exception as exc:
                cleanup_errors.append(str(exc))
        if not groups:
            for session in sorted(owned):
                try:
                    result = call('cleanup-'+session[:8], 'stop', '--session', session, expect=False)
                    if not result.get('ok'):
                        cleanup_errors.append(result.get('error'))
                except Exception as exc:
                    cleanup_errors.append(str(exc))
        if cleanup_errors:
            report.update(ok=False, cleanup_errors=cleanup_errors)
        report['prepare_calls'] = count()
        (root/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
