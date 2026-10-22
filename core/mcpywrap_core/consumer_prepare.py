"""从已解析依赖构造消费者准备计划；查询只读，执行由项目脚本服务管理。"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from .dependencies import DependencyService, canonical_path, read_project, resolve_path
from .prepare_environment import PrepareError, inspect_environment, require_environment
from .source_files import _relative, digest, long_path
from .utils.paths import is_link

EVENTS = ('before_build', 'before_package', 'before_run')
EXCLUDED = {'.git', '.venv', '.mcpy', '.mcpywrap', '.runtime', 'build', 'dist', '__pycache__', '.pytest_cache'}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def options(project, config):
    value = config.get('tool', {}).get('mcpywrap', {}).get('prepare', {})
    if not isinstance(value, dict) or value.keys() - {'python', 'disabled'}:
        raise PrepareError('tool.mcpywrap.prepare 仅支持 python 和 disabled')
    override = value.get('python')
    if override is not None and (not isinstance(override, str) or not override.strip() or '\0' in override):
        raise PrepareError('tool.mcpywrap.prepare.python 必须是已有解释器路径')
    selectors = value.get('disabled', [])
    if not isinstance(selectors, list):
        raise PrepareError('tool.mcpywrap.prepare.disabled 必须是来源选择器数组')
    disabled = []
    for selector in selectors:
        if not isinstance(selector, dict):
            raise PrepareError('disabled 选择器须为 {path=...} 或 {git=..., subdir=...}')
        if set(selector) == {'path'} and isinstance(selector['path'], str) and selector['path'].strip():
            disabled.append({'kind': 'local', 'path': canonical_path(resolve_path(project, selector['path']))})
        elif {'git'} <= set(selector) <= {'git', 'subdir'} and isinstance(selector['git'], str):
            if not selector['git'].startswith(('https://', 'file://')):
                raise PrepareError('disabled.git 必须与已声明的 HTTPS/file:// 来源相同')
            subdir = selector.get('subdir', '.')
            if subdir != '.':
                _relative(subdir, 'disabled.subdir')
            disabled.append({'kind': 'git', 'git': selector['git'], 'subdir': subdir})
        else:
            raise PrepareError('disabled 选择器须为 {path=...} 或 {git=..., subdir=...}')
    return override, disabled


def source_identity(node):
    source = node.source
    if source['kind'] == 'git':
        return {key: source[key] for key in ('kind', 'git', 'rev', 'subdir')}
    return {'kind': source['kind'], 'path': canonical_path(source['path'])}


def _declaration(value, name):
    fields = {'format', 'python', 'requires_python', 'transitive', 'timeout', 'config_key',
              'config_schema', 'config_example'}
    if not isinstance(value, dict) or value.keys() - fields or not {'format', 'python', 'requires_python'} <= value.keys():
        raise PrepareError(name + ': consumer_prepare 需要 format/python/requires_python，或包含未知字段')
    if type(value['format']) is not int or value['format'] != 1:
        raise PrepareError(name + ': 不支持的 consumer_prepare.format，请升级 mcpy。')
    if not isinstance(value['requires_python'], str) or not value['requires_python'].strip():
        raise PrepareError(name + ': requires_python 必须是非空 PEP 440 版本约束')
    try:
        SpecifierSet(value['requires_python'])
    except InvalidSpecifier as exc:
        raise PrepareError(name + ': 无效 requires_python') from exc
    if type(value.get('transitive', False)) is not bool:
        raise PrepareError(name + ': transitive 必须是布尔值')
    timeout = value.get('timeout', 120)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise PrepareError(name + ': timeout 必须在 0–86400 秒之间')
    for key in ('python', 'config_schema', 'config_example'):
        if key in value:
            _relative(value[key], name + '.' + key)
    if Path(value['python']).suffix != '.py':
        raise PrepareError(name + ': python 入口必须是 .py 文件')
    config_key = value.get('config_key')
    if config_key is not None and (not isinstance(config_key, str) or
            not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*', config_key)):
        raise PrepareError(name + ': config_key 必须是普通点分隔表名')
    if 'config_schema' in value and config_key is None:
        raise PrepareError(name + ': config_schema 需要 config_key')
    return dict(value, timeout=timeout, transitive=value.get('transitive', False))


def _file(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise PrepareError('准备工具文件缺失或越出依赖根：' + str(path))
    return long_path(path)


def _schema(path):
    try:
        from jsonschema import Draft202012Validator, SchemaError
        from referencing import Registry
    except ImportError as exc:
        from .host import CapabilityUnavailable
        raise CapabilityUnavailable('json_schema_2020_12', '安装 mcpywrap-core[prepare]，或让宿主提供兼容的 JSON Schema 依赖。') from exc
    try:
        schema = json.loads(path.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(schema)
        if isinstance(schema, dict) and schema.get('$schema', Draft202012Validator.META_SCHEMA['$id']).rstrip('#') != Draft202012Validator.META_SCHEMA['$id'].rstrip('#'):
            raise PrepareError('config_schema 仅支持 JSON Schema Draft 2020-12：' + str(path))
        def check(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('$ref', '$dynamicRef') and isinstance(item, str) and not item.startswith('#'):
                        raise PrepareError('schema 首版仅支持内部引用：' + item)
                    if key not in ('examples', 'default', 'const', 'enum'):
                        check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        check(schema)
        def refuse(uri):
            raise PrepareError('schema 不允许外部引用：' + uri)
        return Draft202012Validator(schema, registry=Registry(retrieve=refuse))
    except (ValueError, SchemaError) as exc:
        if isinstance(exc, PrepareError):
            raise
        raise PrepareError('无效 config_schema %s：%s' % (path, exc)) from exc


def _json_value(value, location):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, dict):
        return {key: _json_value(item, location + '.' + key) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item, '%s[%d]' % (location, index)) for index, item in enumerate(value)]
    raise PrepareError(location + ': 配置值不能表示为标准 JSON（不支持日期、时间或非有限数值）',
                       config_path=location)


def consumer_config(config, provider):
    key = provider['spec'].get('config_key')
    value = config if key else {}
    if key:
        for part in key.split('.'):
            if not isinstance(value, dict):
                raise PrepareError(key + ': 配置路径经过了非表类型', provider=provider['id'])
            value = value.get(part, {})
        if not isinstance(value, dict):
            raise PrepareError(key + ': 配置必须是 TOML 表', provider=provider['id'])
    value = _json_value(value, key or 'config')
    validator = provider.get('validator')
    if validator is not None:
        try:
            errors = sorted(validator.iter_errors(value), key=lambda e: tuple(map(str, e.absolute_path)))
        except Exception as exc:
            raise PrepareError('无法解析 %s 的 schema 引用：%s' % (provider['name'], exc), provider=provider['id']) from exc
        if errors:
            issues = []
            for error in errors:
                location = key + ''.join('[%s]' % p if isinstance(p, int) else '.' + p for p in error.absolute_path)
                if error.validator == 'required':
                    missing = next((p for p in error.validator_value if error.message.startswith(repr(p))), None)
                    if missing:
                        location += '.' + missing
                issues.append({'path': location, 'message': error.message,
                               'description': error.schema.get('description') if isinstance(error.schema, dict) else None})
            raise PrepareError('%s 的消费者配置无效：\n%s' % (provider['name'], '\n'.join(i['path'] + ': ' + i['message'] for i in issues)),
                               'consumer_config_invalid', provider=provider['id'], issues=issues,
                               hint='修改 pyproject.toml 指定字段；配置示例：' + (provider.get('config_example') or '查看依赖作者说明'))
    return value


def source_digest(root):
    """覆盖工具辅助模块及元数据；不把本地环境和生成缓存当工具源码。"""
    root = long_path(Path(root).resolve())
    target = read_project(root).get('tool', {}).get('mcpywrap', {}).get('target_dir')
    output = long_path((root / target).resolve()) if isinstance(target, str) and target else None
    result = hashlib.sha256()
    for directory, dirs, files in os.walk(root, followlinks=False):
        folder = Path(directory)
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED and
                         (output is None or long_path((folder / name).resolve()) != output))
        for name in sorted(dirs + files):
            if name in EXCLUDED:
                continue
            path = folder / name
            if path.suffix in ('.pyc', '.pyo'):
                continue
            if is_link(path):
                raise PrepareError('准备依赖源码不能包含链接：' + str(path))
            if path.is_file():
                relative = path.relative_to(root).as_posix().encode()
                data = path.read_bytes()
                result.update(len(relative).to_bytes(8, 'big') + relative + len(data).to_bytes(8, 'big') + data)
    return result.hexdigest()


class PreparationPlan:
    def __init__(self, project, *, resolved=None, inspect_only=False):
        from .project_scripts import project_snapshot
        self.project = Path(project).resolve()
        self.snapshot = project_snapshot(self.project)
        self.config = read_project(self.project)
        self.manager = resolved
        self.providers, self.issues, self.protected, self.sources, self.files = [], [], {}, {}, {}
        self.complete = True
        self.override, self.disabled = options(self.project, self.config)
        self.environment = None
        self.environment_identity = None
        if self.config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') != 'addon':
            return
        try:
            self.manager = resolved or DependencyService(self.project).resolve(collect_errors=inspect_only)
        except (ValueError, OSError) as exc:
            if not inspect_only:
                raise
            self._issue(exc)
            self.complete = False
            return
        for error in self.manager.errors:
            self._issue(PrepareError(error))
            self.complete = False
        root = self.manager.root_node
        nodes, edges, seen = {}, {}, set()
        def visit(node):
            key = _hash(source_identity(node))
            nodes.setdefault(key, []).append(node)
            edges.setdefault(key, set())
            if id(node) in seen:
                return key
            seen.add(id(node))
            for child in node.children:
                edges[key].add(visit(child))
            return key
        root_key = visit(root)
        direct = {_hash(source_identity(node)) for node in root.children}
        ordered, pending = [], set(nodes)
        while pending:
            ready = sorted(key for key in pending if not (edges[key] & pending))
            if not ready:
                error = PrepareError('准备来源存在循环依赖，不能确定执行顺序')
                if not inspect_only:
                    raise error
                self._issue(error)
                self.complete = False
                break
            ordered.extend(ready)
            pending.difference_update(ready)
        for key in ordered:
            if key == root_key:
                continue
            node = nodes[key][0]
            if node.source['kind'] not in ('local', 'git'):
                continue
            for alias_node in nodes[key]:
                folder = Path(alias_node.addon_pack.path)
                # 所有描述和锁都保护；Git 注册内容也不得在准备中被修改。
                self.protected[str(folder)] = project_snapshot(folder)
                if alias_node.source['kind'] == 'git':
                    self.sources[str(folder)] = ('registered', digest(folder))
            document = read_project(node.addon_pack.path)
            raw = document.get('tool', {}).get('mcpywrap', {}).get('consumer_prepare')
            if raw is None:
                continue
            provider = {'id': key, 'kind': 'consumer_prepare', 'name': node.name,
                        'aliases': sorted({n.name for n in nodes[key]}), 'source': source_identity(node),
                        'direct': key in direct, 'state': 'invalid', 'events': list(EVENTS)}
            self.providers.append(provider)
            try:
                spec = _declaration(raw, node.name)
                provider['spec'] = spec
                disabled = any(all(provider['source'].get(k) == v for k, v in selector.items())
                               for selector in self.disabled)
                provider['state'] = ('disabled' if disabled else
                                     'enabled' if key in direct or spec['transitive'] else 'not_transitive')
                if provider['state'] != 'enabled':
                    continue
                folder = node.descriptor_root
                provider.update(root=str(folder), entry=str(_file(folder, spec['python'])))
                # Git 读取原始描述，避免注册时重写过的目录与项目名成为工具契约。
                original = read_project(folder).get('tool', {}).get('mcpywrap', {}).get('consumer_prepare')
                if original != raw:
                    raise PrepareError(node.name + ': 原始准备声明与已解析依赖不一致，请 sync。')
                for field in ('config_schema', 'config_example'):
                    if field in spec:
                        provider[field] = str(_file(folder, spec[field]))
                if 'config_schema' in provider:
                    provider['validator'] = _schema(Path(provider['config_schema']))
                if 'config_example' in provider:
                    provider['example'] = Path(provider['config_example']).read_text(encoding='utf-8')
                for field in ('entry', 'config_schema', 'config_example'):
                    if field in provider:
                        self.files[provider[field]] = hashlib.sha256(Path(provider[field]).read_bytes()).hexdigest()
                if node.source['kind'] == 'git':
                    # 共享 Git 快照全量只读，不能忽略新写入的缓存或字节码目录。
                    self.sources[str(node.source_root)] = ('git_source', digest(node.source_root))
                else:
                    self.sources[str(folder)] = ('source', source_digest(folder))
            except (ValueError, OSError) as exc:
                provider['state'] = 'invalid'
                if not inspect_only:
                    if isinstance(exc, PrepareError):
                        exc.details.update(provider=key, source=provider['source'])
                    raise
                self._issue(exc, key)
                self.complete = False
        owners = {}
        for provider in self.enabled:
            key = provider['spec'].get('config_key')
            if key and key in owners:
                error = PrepareError('消费者配置 %s 被多个来源使用：%s / %s' %
                                     (key, owners[key]['source'], provider['source']),
                                     providers=[owners[key]['id'], provider['id']])
                if not inspect_only:
                    raise error
                self._issue(error)
                self.complete = False
            if key:
                owners[key] = provider

    def _issue(self, exc, provider=None):
        self.issues.append({'code': getattr(exc, 'code', 'consumer_prepare_unavailable'),
                            'error': str(exc), 'hint': getattr(exc, 'hint', '检查依赖来源并运行 mcpy sync。'),
                            **getattr(exc, 'details', {}), **({'provider': provider} if provider else {})})

    @property
    def enabled(self):
        return [p for p in self.providers if p['state'] == 'enabled']

    @property
    def requirements(self):
        return [{'provider': p['id'], 'name': p['name'], 'requires_python': p['spec']['requires_python']}
                for p in self.enabled]

    @property
    def budget(self):
        # 为每个监督进程留出取消/回收余量。
        return sum(p['spec']['timeout'] + 8 for p in self.enabled)

    def environment_status(self):
        if self.environment is None:
            self.environment = inspect_environment(self.project, self.requirements, self.override)
        return self.environment

    def preflight(self):
        require_environment(self.environment_status())
        self.environment_identity = self._environment_identity()
        self.check()

    def _environment_identity(self):
        if not self.enabled:
            return None
        from .host import current_host
        provider = current_host().environment_provider
        if provider is not None:
            # Normalize to an immutable snapshot, so mutable host records cannot
            # silently change the previously captured environment identity.
            return json.dumps(provider.identity(self.environment_status()), sort_keys=True, allow_nan=False)
        executable = Path(self.environment_status()['python'])
        try:
            stat = executable.stat()
            config = executable.parent.parent / 'pyvenv.cfg'
            return (str(executable.resolve()), stat.st_size, stat.st_mtime_ns,
                    hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else None)
        except OSError as exc:
            raise PrepareError('准备工具解释器在操作期间不可用：' + str(executable), 'script_config_changed') from exc

    def check(self):
        from .project_scripts import project_snapshot
        changed = self.snapshot != project_snapshot(self.project)
        if self.environment_identity is not None:
            changed = changed or self.environment_identity != self._environment_identity()
        for root, snapshot in self.protected.items():
            changed = changed or snapshot != project_snapshot(root)
        for root, (kind, expected) in self.sources.items():
            actual = source_digest(root) if kind == 'source' else digest(root)
            changed = changed or expected != actual
        for path, expected in self.files.items():
            file = Path(path)
            changed = changed or not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected
        if changed:
            raise PrepareError('准备期间项目配置、依赖锁、包身份或工具源码已变化；本次操作停止。',
                               'script_config_changed', hint='保存配置和依赖源码后重新执行；不会混用两份准备计划。')

    def token(self):
        # 只保存摘要，不把源码内容或完整宿主配置写入会话记录。
        return _hash({'snapshot': {p: hashlib.sha256(v).hexdigest() if v is not None else None
                                   for p, v in self.snapshot.items()},
                      'protected': {root: {p: hashlib.sha256(v).hexdigest() if v is not None else None
                                          for p, v in snapshot.items()} for root, snapshot in self.protected.items()},
                      'sources': self.sources, 'files': self.files, 'providers': self.rows(),
                      'environment': self.environment_status(), 'interpreter_identity': self._environment_identity()})

    def rows(self):
        rows = []
        for provider in self.providers:
            row = dict(provider.get('spec', {}))
            row.update({k: v for k, v in provider.items() if k not in ('validator', 'spec')})
            rows.append(row)
        return rows

    def inspect(self):
        issues = list(self.issues)
        for provider in self.enabled:
            try:
                consumer_config(self.config, provider)
            except PrepareError as exc:
                issues.append({'code': exc.code, 'error': str(exc), 'hint': exc.hint, **exc.details})
        try:
            require_environment(self.environment_status())
        except PrepareError as exc:
            issues.append({'code': exc.code, 'error': str(exc), 'hint': exc.hint, **exc.details})
        return {'complete': self.complete, 'ready': self.complete and not issues,
                'consumer_prepare': self.rows(), 'environment': self.environment_status(), 'diagnostics': issues}

    def execute(self, event, *, cancel=None, progress=None, after_task=None):
        from .project_scripts import _execute, ScriptError
        results = []
        for provider in self.providers:
            if provider['state'] != 'enabled':
                from .command_context import report_warning
                report_warning('%s：消费者准备%s。' %
                               (provider['name'], '已显式停用' if provider['state'] == 'disabled' else '未开启传递执行'))
                continue
            if cancel and cancel():
                raise ScriptError('消费者准备已取消', 'script_cancelled', provider=provider['id'])
            self.check()
            value = consumer_config(self.config, provider)
            directory = self.project / '.mcpy/scripts'
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='config-', dir=directory) as temporary:
                config_path = Path(temporary) / 'consumer.json'
                config_path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
                spec = {'command': [self.environment_status()['python'], '-u', provider['entry']],
                        'python': True, 'timeout': provider['spec']['timeout'], 'kind': 'consumer_prepare',
                        'provider': provider['id'], 'source': provider['source'],
                        'env': {'PYTHONDONTWRITEBYTECODE': '1', 'MCPY_DEPENDENCY_ROOT': provider['root'],
                                'MCPY_PROVIDER_ID': provider['id'], 'MCPY_CONSUMER_CONFIG': str(config_path)}}
                try:
                    results.append(_execute(self.project, provider['name'], spec, event, (), cancel=cancel, progress=progress))
                except ScriptError as exc:
                    exc.hint = ('查看 script_log 中的业务诊断。工具解释器：%s；如缺少第三方库，使用该解释器的 '
                                '-m pip install <作者要求的发行包>，不要安装到 mcpy 工具环境。' % spec['command'][0])
                    raise
            self.check()
            if after_task:
                after_task()
        return results


def guidance(project, *, resolved=None):
    """依赖维护后的说明不执行代码，也不让业务配置缺项回滚依赖恢复。"""
    import click
    try:
        result = PreparationPlan(project, resolved=resolved, inspect_only=True).inspect()
    except (ValueError, OSError) as exc:
        result = {'complete': False, 'ready': False, 'consumer_prepare': [],
                  'diagnostics': [{'error': str(exc)}]}
    for provider in result['consumer_prepare']:
        click.echo('消费者准备：%s（%s）' % (provider['name'], provider['state']), err=True)
        if provider.get('example'):
            click.echo('配置示例：\n' + provider['example'], err=True)
    for issue in result['diagnostics']:
        click.echo(issue['error'], err=True)
    if result['consumer_prepare'] and not result['ready']:
        click.echo('先运行 mcpy sync 准备环境，并按上述提示填写配置。', err=True)
    return result
