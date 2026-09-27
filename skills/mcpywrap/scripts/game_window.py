"""兼容入口：通过公开 CLI 在本机或远端截图、输入；Win32 实现仅维护在包中。"""
import argparse
import json
import os
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--command', default='mcpy')
    parser.add_argument('--remote')
    parser.add_argument('--local', action='store_true')
    parser.add_argument('action', choices=['screenshot', 'key', 'mouse'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER,
                        help='透传 CLI 参数；mouse 的第一个参数为 click/drag/relative 等动作')
    args = parser.parse_args(argv)
    command = [args.command, '--project', args.project, '--non-interactive']
    if args.remote:
        command += ['--remote', args.remote]
    if args.local:
        command += ['--local']
    command += [args.action, '--session', args.session, *args.arguments, '--json']
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                encoding='utf-8-sig', errors='replace', timeout=120,
                                env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        if '--help' in args.arguments:
            print(result.stdout, end='')
            return result.returncode
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError('CLI 未返回 JSON 对象')
        if result.stderr:
            print(result.stderr, file=sys.stderr, end='')
        print(json.dumps(data, ensure_ascii=True))
        return result.returncode
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'session': args.session,
                          'hint': '结果可能未知；请查询会话并截图，勿盲目重复输入。'}, ensure_ascii=True))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
