"""使用统一公开 CLI 无交互验收项目、日志和双端 Python，结束后关闭自己启动的会话。"""
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
    parser.add_argument('--remote', help='Windows 局域网服务地址，也可使用 MCPY_REMOTE')
    parser.add_argument('--local', action='store_true', help='强制本机验证')
    parser.add_argument('--game', action='store_true', help='验证新的本地世界')
    parser.add_argument('--connect', metavar='HOST', help='验证临时网络目标，不打包或读取项目配置')
    parser.add_argument('--port', type=int, default=19132)
    parser.add_argument('--mcs-auth', action='store_true', help='本次游戏验证显式使用已登录的 MCS 身份')
    parser.add_argument('--client-file', type=Path, help='世界就绪后只执行一次的客户端 Python 2 验收脚本')
    parser.add_argument('--server-file', type=Path, help='世界就绪后只执行一次的服务端 Python 2 验收脚本，仅本地世界')
    parser.add_argument('--expect-log', action='append', default=[])
    parser.add_argument('--timeout', type=float, default=90)
    args = parser.parse_args(argv)
    game = args.game or bool(args.connect)
    if args.timeout <= 0 or not 1 <= args.port <= 65535:
        parser.error('timeout 必须为正数，port 必须在 1–65535 之间')
    if (args.expect_log or args.mcs_auth or args.client_file or args.server_file) and not game:
        parser.error('日志、身份和 Python 验收参数需要 --game 或 --connect')
    if args.connect and args.game:
        parser.error('--connect 和 --game 请选择一种')
    if args.server_file and args.connect:
        parser.error('--server-file 仅用于自己的本地测试世界')
    for script in (args.client_file, args.server_file):
        if script and not script.is_file():
            parser.error('验收脚本不存在: ' + str(script))
    project = str(Path(args.project).resolve())
    session = None
    report = {'ok': False, 'project': project, 'error': None}

    def invoke(*arguments, allow_failure=False):
        routing = ['--remote', args.remote] if args.remote else []
        if args.local:
            routing += ['--local']
        proc = subprocess.run([args.command, '--project', project, '--non-interactive',
                               *routing, *arguments, '--json'], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, encoding='utf-8-sig', errors='replace', timeout=180,
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        try:
            data = json.loads(proc.stdout)
        except ValueError as exc:
            raise ValueError(f'命令未返回有效 JSON: {proc.stderr[-2000:]}') from exc
        if (proc.returncode or not data.get('ok')) and not allow_failure:
            raise ValueError(data.get('error') or proc.stderr[-2000:] or '命令失败')
        return data

    def settle_client(result, deadline):
        # 冷启动可能超过单次等待窗口；只查询原请求，不重复执行代码。
        queued = report.get('capabilities', {}).get('python', {}).get('client_queue') is True
        while result.get('state') in ('queued', 'running') and queued and result.get('request_id'):
            if time.monotonic() >= deadline:
                break
            time.sleep(.25)
            result = invoke('runtime', 'py-result', result['request_id'], '--session', session,
                            allow_failure=True)
        return result

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
            if started.get('already_running'):
                raise ValueError('启动复用了已有会话；不执行验收，也不停止他人的会话')
            session = started['session']
            report.update(session=session, log_path=started['log_path'],
                          engine_log_path=started.get('engine_log_path'), verified='process-started')
            if args.game:
                report['capabilities'] = invoke('runtime', 'capabilities', '--session', session)
            if args.client_file or args.server_file:
                # 就绪轮询只读；任意验收脚本执行一次，未知结果不重试。
                ready_code = """try:
    import mod.client.extraClientApi as api, gui
    _result = api.GetLevelId() not in (None, -1, '-1') and gui.get_top_screen() == 'hud_screen'
except (ImportError, AttributeError):
    _result = False
"""
                deadline = time.monotonic() + args.timeout
                while True:
                    probe = invoke('runtime', 'py', '--session', session, '--code', ready_code,
                                   allow_failure=True)
                    probe = settle_client(probe, deadline)
                    if probe.get('state') == 'completed' and probe.get('value') is True:
                        break
                    if probe.get('state') not in ('completed', 'unavailable'):
                        raise ValueError('就绪探针结果未确认: ' + str(probe))
                    status = invoke('status', '--session', session)
                    if status['state'] not in ('starting', 'running'):
                        raise ValueError('游戏提前退出')
                    if time.monotonic() >= deadline:
                        raise ValueError('等待世界就绪超时')
                    time.sleep(.5)
                report['probes'] = {}
                for side, script in (('client', args.client_file), ('server', args.server_file)):
                    if script:
                        result = invoke('runtime', 'py', '--session', session, '--side', side,
                                        '--file', str(script.resolve()), allow_failure=True)
                        if side == 'client':
                            result = settle_client(result, time.monotonic() + args.timeout)
                        report['probes'][side] = result
                        if not result.get('ok') or result.get('state') != 'completed' or result.get('side') != side:
                            raise ValueError(side + ' 验收脚本未成功完成；不会重试')
                report['verified'] = 'python-probes'
            deadline = time.monotonic() + args.timeout
            remaining = set(args.expect_log)
            while remaining and time.monotonic() < deadline:
                text = invoke('logs', '--session', session, '--tail', '10000')['text']
                remaining = {marker for marker in remaining if marker not in text}
                if not remaining:
                    report['verified'] = 'python-probes-and-log-markers' if report.get('probes') else 'log-markers'
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
