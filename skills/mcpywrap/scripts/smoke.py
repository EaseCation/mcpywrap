"""组合公开 CLI 做验证；游戏画面操作由 Agent 的 Computer Use 完成。"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--command', default='mcpy', help='bootstrap 返回的 mcpy 命令路径')
    parser.add_argument('--game', action='store_true')
    parser.add_argument('--expect-log', action='append', default=[])
    parser.add_argument('--timeout', type=float, default=90)
    args = parser.parse_args()
    if args.timeout <= 0 or (args.expect_log and not args.game):
        parser.error('timeout 必须为正数，expect-log 需要 --game')
    project = str(Path(args.project).resolve())
    session = None
    report = {'ok': False, 'project': project, 'error': None}

    def invoke(*arguments, allow_failure=False):
        proc = subprocess.run([args.command, '--project', project, '--non-interactive',
                               *arguments, '--json'], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180,
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        try:
            data = json.loads(proc.stdout)
        except ValueError as exc:
            raise ValueError(f'命令未返回有效 JSON: {proc.stderr[-2000:]}') from exc
        if (proc.returncode or not data.get('ok')) and not allow_failure:
            raise ValueError(data.get('error') or proc.stderr[-2000:] or '命令失败')
        return data

    try:
        diagnosis = invoke('doctor', allow_failure=True)
        report['engine_ready'] = diagnosis.get('ok', False)
        package = invoke('package')
        artifact = Path(package['artifact'])
        if not artifact.is_file():
            raise ValueError('命令成功但 ZIP 文件不存在')
        report['artifact'] = str(artifact)
        if args.game:
            if not report['engine_ready']:
                raise ValueError(diagnosis.get('error') or str(diagnosis.get('resources')))
            started = invoke('run', '--new', '--no-gui', '--detach')
            session = started['session']
            report.update(session=session, log_path=started['log_path'], verified='process-started')
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
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
