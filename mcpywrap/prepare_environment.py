"""消费者准备工具的解释器检查与显式 sync 环境创建。"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from .project_scripts import ScriptError


class PrepareError(ScriptError):
    def __init__(self, message, code='consumer_prepare_invalid', *, hint=None, **details):
        super().__init__(message, code, **details)
        self.hint = hint or '修复指定的依赖声明或业务配置；使用 mcpy script list --effective --json 查看来源。'


def interpreter_path(project, override=None):
    # 不能 resolve 最后的符号链接，否则 .venv/bin/python 会退回基础解释器。
    if override:
        return Path(os.path.abspath(Path(project) / override))
    return Path(project) / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def probe(path):
    if not Path(path).is_file():
        return None
    try:
        result = subprocess.run([str(path), '-I', '-B', '-S', '-c',
                                 'import json,sys;print(json.dumps(list(sys.version_info[:3])))'],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        values = json.loads(result.stdout) if not result.returncode else None
        if not isinstance(values, list) or len(values) != 3 or any(type(v) is not int for v in values):
            return None
        return '.'.join(map(str, values))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def compatible(version, requirements):
    return version is not None and all(SpecifierSet(item['requires_python']).contains(version)
                                      for item in requirements)


def inspect_environment(project, requirements, override=None):
    path = interpreter_path(project, override)
    if not requirements:
        return {'state': 'not_required', 'python': None, 'version': None, 'requirements': []}
    version = probe(path)
    state = 'ready' if compatible(version, requirements) else ('missing' if not path.is_file() else 'incompatible')
    return {'state': state, 'python': str(path), 'version': version, 'requirements': requirements,
            'override': bool(override)}


def require_environment(environment):
    if environment['state'] in ('ready', 'not_required'):
        return
    requirements = ', '.join('%s: %s' % (r['name'], r['requires_python']) for r in environment['requirements'])
    hint = ('请修复 tool.mcpywrap.prepare.python 指向的现有环境。' if environment['override'] else
            '运行 mcpy sync 自动使用本机兼容 Python 创建 .venv；已有环境不会被自动重建。')
    raise PrepareError('消费者工具环境未就绪：%s（检测版本：%s）；要求 %s' %
                       (environment['python'], environment['version'] or '不可用', requirements),
                       'prepare_environment_unavailable', hint=hint, environment=environment)


def candidates():
    paths = {os.path.abspath(sys.executable)}
    for directory in os.get_exec_path():
        try:
            for path in Path(directory).iterdir():
                if os.name == 'nt' and str(path.parent).lower().endswith('\\microsoft\\windowsapps'):
                    continue  # 跳过可能打开应用商店的未安装解释器别名。
                if re.fullmatch(r'python(?:3(?:\.\d+)?)?(?:\.exe)?', path.name, re.I) and path.is_file():
                    paths.add(os.path.abspath(path))
        except OSError:
            continue
    launcher = shutil.which('py') if os.name == 'nt' else None
    if launcher:
        try:
            result = subprocess.run([launcher, '-0p'], stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                match = re.search(r'([A-Za-z]:\\.*?python(?:\d+(?:\.\d+)?)?\.exe)\s*$', line, re.I)
                if match:
                    paths.add(match.group(1))
        except (OSError, subprocess.SubprocessError):
            pass
    found = [(path, probe(path)) for path in sorted(paths)]
    # 版本最高者优先，同版本按路径稳定选择，并在 sync 结果记录。
    return sorted(((p, v) for p, v in found if v), key=lambda item: (-Version(item[1]).major,
                  -Version(item[1]).minor, -Version(item[1]).micro, os.path.normcase(item[0])))


def ensure_environment(project, requirements, override=None):
    from .project_scripts import _execute
    project = Path(project).resolve()
    environment = inspect_environment(project, requirements, override)
    if environment['state'] in ('ready', 'not_required'):
        return dict(environment, created=False)
    destination = project / '.venv'
    if override or os.path.lexists(destination):
        require_environment(environment)
    found = candidates()
    selected = next(((path, version) for path, version in found if compatible(version, requirements)), None)
    if selected is None:
        raise PrepareError('依赖已恢复，但没有满足全部消费者工具要求的本机 Python。',
                           'prepare_python_unavailable', environment=environment,
                           candidates=[{'python': p, 'version': v} for p, v in found],
                           hint='安装满足所列要求的 Python 后重新运行 mcpy sync，或指定 prepare.python 的已有环境；不会自动下载。')
    # 原地创建保证 venv 的启动器路径正确；失败保留现场供明确处理，不覆盖已有目录。
    destination.mkdir()
    try:
        record = _execute(project, '创建消费者工具环境',
                          {'command': [selected[0], '-I', '-m', 'venv', str(destination)],
                           'env': {'PYTHONDONTWRITEBYTECODE': '1'}, 'timeout': 120, 'python': False,
                           'kind': 'prepare_environment'}, 'sync', ())
    except ScriptError as exc:
        exc.hint = '环境创建未完成，已保留 .venv 和日志；确认进程退出后检查该目录，再重新 sync。'
        raise
    environment = inspect_environment(project, requirements)
    require_environment(environment)
    ignore = project / '.gitignore'
    content = ignore.read_text(encoding='utf-8') if ignore.exists() else ''
    if '.venv/' not in content.splitlines():
        ignore.write_text(content + ('\n' if content and not content.endswith('\n') else '') + '.venv/\n', encoding='utf-8')
    return dict(environment, created=True, created_with=selected[0], script=record)
