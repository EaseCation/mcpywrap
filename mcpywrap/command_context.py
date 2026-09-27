"""CLI 的项目上下文、交互策略和统一输出；不改变进程工作目录。"""
import contextlib
import contextvars
import json
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path

import click


@dataclass
class CommandContext:
    project: Path
    non_interactive: bool = False
    json_output: bool = False
    remote: str = None
    local: bool = False


_context = contextvars.ContextVar('mcpy_context', default=None)


def project_dir():
    current = _context.get()
    return current.project if current else Path.cwd()


def non_interactive():
    current = _context.get()
    return bool(current and current.non_interactive) or not sys.stdin.isatty()


def json_output():
    current = _context.get()
    return bool(current and current.json_output)


def human_interaction():
    current = _context.get()
    return current is not None and not non_interactive() and not json_output()


@contextlib.contextmanager
def project_scope(path):
    previous = _context.get()
    token = _context.set(CommandContext(Path(path).resolve(),
                                       previous.non_interactive if previous else False,
                                       previous.json_output if previous else False))
    try:
        yield
    finally:
        _context.reset(token)


def require_project():
    if not (project_dir() / 'pyproject.toml').is_file():
        raise click.ClickException('未找到 pyproject.toml；请先执行 mcpy init --type addon 或 --type map')


class OperationCommand(click.Command):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.params.append(click.Option(['--json', 'json_output'], is_flag=True,
                                        help='输出单个 JSON 结果'))

    def invoke(self, ctx):
        ctx.params.pop('json_output', None)
        from .remote.client import routed_command
        routed, result = routed_command(ctx.info_name, ctx.params)
        if routed:
            return result
        return super().invoke(ctx)


class OperationGroup(click.Group):
    def main(self, args=None, prog_name=None, complete_var=None, standalone_mode=True, **extra):
        args = list(sys.argv[1:] if args is None else args)
        structured = '--json' in args and '--help' not in args
        output = sys.stdout
        state = CommandContext(Path.cwd(), '--non-interactive' in args, structured)
        token = _context.set(state)
        code, result = 0, None
        try:
            with contextlib.redirect_stdout(sys.stderr) if structured else contextlib.nullcontext():
                try:
                    result = super().main(args=args, prog_name=prog_name, complete_var=complete_var,
                                          standalone_mode=False, **extra)
                    if isinstance(result, dict) and result.get('ok') is False:
                        code = 1
                except click.ClickException as exc:
                    code = exc.exit_code
                    result = {'ok': False, 'error': exc.format_message(),
                              'hint': '使用 mcpy <命令> --help 查看所需参数。'}
                except (KeyboardInterrupt, click.Abort):
                    code = 130
                    result = {'ok': False, 'error': '操作已中断', 'hint': None}
                except (ValueError, OSError) as exc:
                    code = 1
                    result = {'ok': False, 'error': str(exc),
                              'hint': getattr(exc, 'hint', '请核对项目配置和相关文件路径。')}
                    if getattr(exc, 'code', None):
                        result['code'] = exc.code
                except Exception as exc:
                    code = 1
                    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='mcpy-error-',
                                                     suffix='.log', delete=False) as log:
                        traceback.print_exc(file=log)
                    result = {'ok': False, 'error': str(exc), 'hint': f'意外错误详情: {log.name}'}
            if isinstance(result, int):
                code = result
                result = None
            if structured:
                data = {'ok': code == 0, 'error': None, 'hint': None}
                if isinstance(result, dict):
                    data.update(result)
                # ASCII JSON survives both GBK consoles and UTF-8 subprocess pipes losslessly.
                click.echo(json.dumps(data, ensure_ascii=True), file=output)
            elif code:
                click.echo('错误: ' + str((result or {}).get('error') or '操作失败'), err=True)
                if (result or {}).get('hint'):
                    click.echo(result['hint'], err=True)
            elif isinstance(result, dict):
                # 保留命令原有进度输出，为交接和产物结果补充可读信息。
                for key, value in result.items():
                    if key not in ('ok', 'error', 'hint') and value is not None:
                        click.echo(f'{key}: {value}')
        finally:
            _context.reset(token)
        if standalone_mode:
            raise SystemExit(code)
        if code:
            raise click.exceptions.Exit(code)
        return result


def configure_context(project, interactive_disabled, remote=None, local=False):
    current = _context.get()
    current.remote, current.local = remote, local
    current.project = Path(project or os.getcwd()).expanduser().resolve()
    current.non_interactive = interactive_disabled or not sys.stdin.isatty()
    if not current.project.is_dir():
        raise click.UsageError(f'项目目录不存在: {current.project}')


def remote_url():
    """Resolve only for game operations; local project commands never depend on a remote."""
    state = _context.get()
    if state and state.local:
        return None
    if state and state.remote is not None:
        return state.remote
    if os.environ.get('MCPY_REMOTE'):
        return os.environ['MCPY_REMOTE']
    path = project_dir()/'pyproject.toml'
    if path.is_file():
        import tomli
        try:
            with path.open('rb') as stream:
                return tomli.load(stream).get('tool', {}).get('mcpywrap', {}).get('remote_url')
        except tomli.TOMLDecodeError:
            # connect intentionally ignores unrelated malformed project configuration.
            return None
    return None
