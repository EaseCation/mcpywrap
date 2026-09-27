"""Install/reuse mcpywrap with uv and report local and optional Windows capabilities."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

GAME_CAPABILITIES = {'network', 'network-sessions', 'mcs-auth', 'screenshot', 'key', 'mouse'}


def invoke(command, timeout=30):
    return subprocess.run([str(v) for v in command], stdin=subprocess.DEVNULL, capture_output=True,
                          encoding='utf-8-sig', errors='replace', timeout=timeout,
                          env=dict(os.environ, PYTHONIOENCODING='utf-8'))


def capabilities(command, remote=None, local=False):
    help_result = invoke([command, '--help'])
    help_text = help_result.stdout
    basic = ('--project', '--non-interactive', '--json', 'status', 'logs', 'stop', 'package')
    if help_result.returncode or any(k not in help_text for k in basic):
        raise ValueError('现有 CLI 缺少基础能力；显式选择版本并使用 --upgrade')
    local_flag = ['--local'] if '--local' in help_text else []
    run_help = invoke([command, 'run', '--help']).stdout
    features = ['project', 'json', 'sessions', 'package']
    add_help = invoke([command, 'add', '--help']).stdout
    if '--git' in add_help and '--ref' in add_help:
        features.append('git-dependencies')
    if '--framework' in add_help:
        features.append('framework-presets')
    if '--detach' not in run_help or '--no-gui' not in run_help:
        raise ValueError('现有 CLI 不支持后台会话，请显式升级')
    if re.search(r'^\s+connect\s', help_text, re.M):
        features.append('network')
        if '--detach' in invoke([command, 'connect', '--help']).stdout:
            features.append('network-sessions')
    for name in ('screenshot', 'key', 'mouse', 'serve'):
        if re.search(r'^\s+'+name+r'\s', help_text, re.M) and (name != 'serve' or os.name == 'nt'):
            features.append(name)
    auth = {'supported': '--mcs-auth' in run_help, 'component_available': None}
    if auth['supported']:
        features.append('mcs-auth')
        if '--mcs-auth' in invoke([command, 'doctor', '--help']).stdout:
            result = invoke([command, *local_flag, '--non-interactive', 'doctor', '--mcs-auth', '--json'])
            try:
                auth.update(json.loads(result.stdout).get('mcs_auth', {}))
            except ValueError:
                auth['hint'] = '组件诊断未返回有效 JSON，请运行 doctor --mcs-auth --json'
    remote_info = None
    if '--remote' in help_text:
        features.append('remote-client')
        # Honors environment and project configuration through the public CLI.
        routing = ['--local'] if local else ['--remote', remote] if remote else []
        result = invoke([command, *routing, '--non-interactive',
                         'doctor', '--capabilities', '--json'])
        try:
            result_data = json.loads(result.stdout)
            if result_data.get('execution') == 'remote' or not result_data.get('ok'):
                remote_info = result_data
        except ValueError:
            remote_info = {'ok': False, 'error': '远端能力检查未返回有效 JSON'}
    elif not local and (remote or os.environ.get('MCPY_REMOTE')):
        remote_info = {'ok': False, 'error': '当前 CLI 缺少远程路由能力，请显式升级'}
    local_features = features if os.name == 'nt' else [f for f in features if f not in GAME_CAPABILITIES]
    return {'capabilities': features, 'local_capabilities': local_features, 'local_platform': sys.platform, 'mcs_auth': auth,
            'remote': remote_info}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--version')
    source.add_argument('--git-ref')
    source.add_argument('--editable-path')
    parser.add_argument('--python', default='3.12')
    parser.add_argument('--upgrade', action='store_true')
    parser.add_argument('--remote')
    parser.add_argument('--local', action='store_true', help='只检查本机，忽略已配置的远端')
    parser.add_argument('--require-capability', action='append', default=[])
    args = parser.parse_args(argv)
    report = {'ok': False, 'error': None}
    try:
        uv = shutil.which('uv')
        if not uv:
            raise ValueError('需要 uv：https://docs.astral.sh/uv/getting-started/installation/')
        result = invoke([uv, 'tool', 'dir', '--bin'])
        if result.returncode:
            raise ValueError('无法查询 uv 工具目录')
        command = Path(result.stdout.strip())/('mcpy.exe' if os.name == 'nt' else 'mcpy')
        if command.is_file() and not args.upgrade:
            version = invoke([command, '--version']).stdout.strip()
            if args.git_ref or args.editable_path or (args.version and not version.endswith(' '+args.version)):
                raise ValueError('更换已有安装的来源或版本需要 --upgrade')
        else:
            arguments = [uv, 'tool', 'install', '--python', args.python]
            if args.upgrade:
                arguments += ['--force', '--upgrade']
            if args.git_ref:
                if not re.fullmatch(r'[0-9a-fA-F]{40}', args.git_ref):
                    raise ValueError('GitRef 必须是完整的 40 位提交 SHA')
                arguments += ['git+https://github.com/EaseCation/mcpywrap.git@'+args.git_ref]
            elif args.editable_path:
                path = Path(args.editable_path).expanduser().resolve()
                if not (path/'pyproject.toml').is_file():
                    raise ValueError('EditablePath 缺少 pyproject.toml')
                arguments += ['--editable', str(path)]
            else:
                arguments += ['mcpywrap'+('=='+args.version if args.version else '')]
            result = invoke(arguments, timeout=600)
            print(result.stdout+result.stderr, file=sys.stderr)
            if result.returncode:
                raise ValueError('uv 安装失败，请检查 stderr')
            version = invoke([command, '--version']).stdout.strip()
        report.update(command=str(command), version=version, **capabilities(command, args.remote, args.local))
        remote = report.get('remote')
        for required in args.require_capability:
            game_capability = required in GAME_CAPABILITIES
            location = '本机'
            if remote is not None and game_capability:
                location = '远端 Windows'
                if not remote.get('ok'):
                    raise ValueError(remote.get('error') or '远端能力不可用')
                available = remote.get('capabilities', [])
                auth = remote.get('mcs_auth', {})
                required = 'network-sessions' if required == 'network' else required
            else:
                available, auth = report['local_capabilities'], report['mcs_auth']
            if required not in available:
                if remote is None and game_capability and os.name != 'nt':
                    raise ValueError('游戏能力需要 Windows 执行端；请用 --remote 配置服务地址，或先只完成本机项目安装')
                if required == 'serve' and os.name != 'nt':
                    raise ValueError('serve 仅能在 Windows 控制台启动；macOS 请检查 remote-client 和远端能力')
                raise ValueError(location+'缺少所需能力: '+required+'；请显式更新该端 CLI')
            if required == 'mcs-auth' and auth.get('component_available') is not True:
                raise ValueError(location+'的 MCS 身份组件缺失或无法检查；请在该端使用包含组件的发布构建或准备开发组件')
        report['ok'] = True
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        report['error'] = str(exc)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
