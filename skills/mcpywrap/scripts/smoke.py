"""组合公开 CLI 做验证；截图和按键使用 game_window.py，复杂操作交给 Computer Use。"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--command', default='mcpy', help='bootstrap 返回的 mcpy 命令路径')
    parser.add_argument('--game', action='store_true', help='验证新的本地世界')
    parser.add_argument('--connect', metavar='HOST', help='验证临时网络目标，不打包或读取项目配置')
    parser.add_argument('--port', type=int, default=19132)
    parser.add_argument('--mcs-auth', action='store_true', help='本次游戏验证显式使用已登录的 MCS 身份')
    parser.add_argument('--expect-log', action='append', default=[])
    parser.add_argument('--timeout', type=float, default=90)
    args = parser.parse_args(argv)
    game = args.game or bool(args.connect)
    if args.timeout <= 0 or not 1 <= args.port <= 65535:
        parser.error('timeout 必须为正数，port 必须在 1–65535 之间')
    if (args.expect_log or args.mcs_auth) and not game:
        parser.error('expect-log/mcs-auth 需要 --game 或 --connect')
    if args.connect and args.game:
        parser.error('--connect 和 --game 请选择一种')
    project = str(Path(args.project).resolve())
    session = None
    report = {'ok': False, 'project': project, 'error': None}

    def invoke(*arguments, allow_failure=False):
        proc = subprocess.run([args.command, '--project', project, '--non-interactive',
                               *arguments, '--json'], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding='utf-8-sig', errors='replace', timeout=180,
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        try:
            data = json.loads(proc.stdout)
        except ValueError as exc:
            raise ValueError(f'命令未返回有效 JSON: {proc.stderr[-2000:]}') from exc
        if (proc.returncode or not data.get('ok')) and not allow_failure:
            raise ValueError(data.get('error') or proc.stderr[-2000:] or '命令失败')
        return data

    try:
        # connect deliberately ignores project configuration; its own preflight diagnoses resources.
        if not args.connect:
            diagnosis = invoke('doctor', allow_failure=True)
            report['engine_ready'] = diagnosis.get('ok', False)
        if not args.connect:
            package = invoke('package')
            artifact = Path(package['artifact'])
            if not artifact.is_file():
                raise ValueError('命令成功但 ZIP 文件不存在')
            report['artifact'] = str(artifact)
        if game:
            if not args.connect and not report['engine_ready']:
                raise ValueError(diagnosis.get('error') or str(diagnosis.get('resources')))
            command = (['connect', args.connect, '--port', str(args.port)] if args.connect else
                       ['run', '--new', '--no-gui'])
            command.append('--detach')
            if args.mcs_auth:
                command.append('--mcs-auth')
            started = invoke(*command)
            session = started['session']
            report.update(session=session, log_path=started['log_path'],
                          engine_log_path=started.get('engine_log_path'), verified='process-started')
            deadline = time.monotonic() + args.timeout
            remaining = set(args.expect_log)
            while remaining and time.monotonic() < deadline:
                text = invoke('logs', '--session', session, '--tail', '10000')['text']
                remaining = {marker for marker in remaining if marker not in text}
                if not remaining:
                    report['verified'] = 'log-markers'
                    break
                status = invoke('status', '--session', session)
                if status['state'] not in ('starting', 'running'):
                    raise ValueError('游戏提前退出，未找到所有加载标记')
                time.sleep(0.5)
            if remaining:
                raise ValueError('等待加载标记超时: ' + ', '.join(sorted(remaining)))
        report['ok'] = True
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        report['error'] = str(exc)
    finally:
        if session:
            try:
                report['log_tail'] = invoke('logs', '--session', session, '--tail', '100')['text']
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                report['log_error'] = str(exc)
            try:
                invoke('stop', '--session', session)
                report['stopped'] = True
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                report.update(ok=False, stop_error=str(exc))
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
