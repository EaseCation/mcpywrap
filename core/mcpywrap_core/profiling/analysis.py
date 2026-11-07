"""把 mcpy-tracy-report 的原始统计整理为面向开发者与 Agent 的摘要、对比与文本。

游戏内置 Tracy 为每个 Python 函数生成区段：名称为函数名，文件为部署后的 .py 路径，行号为 def 行；
Python 内置函数（如 time.time）也有区段，文件为模块名、行号为 0。
"""
import json
import re
import subprocess
from pathlib import Path

from ..engines.host import EngineError
from . import tools

MAIN_LOOP = 'Main Update'
SERVER_TICK = 'serverUpdate'
REPORT_SCHEMA = 1


def report_path(trace):
    trace = Path(trace)
    return trace.with_name(trace.name + '.report.json')


def load(trace):
    """读取或生成原始报告；与采集文件同目录缓存，采集文件更新后重新生成。"""
    trace = Path(trace).expanduser().resolve()
    if not trace.is_file():
        raise EngineError('采集文件不存在：' + str(trace), 'trace_missing')
    cache = report_path(trace)
    executable = tools.require('mcpy-tracy-report')
    # 缓存绑定工具包摘要，工具更新后重新生成
    identity = tools.installed_identity()
    if cache.is_file() and cache.stat().st_mtime >= trace.stat().st_mtime:
        try:
            data = json.loads(cache.read_text(encoding='utf-8'))
            if data.get('schema') == REPORT_SCHEMA and data.get('mcpy_tools') == identity:
                return data
        except ValueError:
            pass
    command = [str(executable), str(trace)]
    try:
        done = subprocess.run(command, capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        raise EngineError('采集文件分析超时', 'report_failed') from None
    if done.returncode != 0:
        raise EngineError('采集文件分析失败：' + done.stderr.decode('utf-8', 'replace').strip()[-400:], 'report_failed')
    try:
        data = json.loads(done.stdout.decode('utf-8', 'replace'))
    except ValueError:
        raise EngineError('分析工具输出无效', 'report_failed') from None
    data['mcpy_tools'] = identity
    try:
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass
    return data


def classify(zone):
    file = zone.get('file') or ''
    if file.lower().endswith('.py'):
        return 'script'
    if zone.get('line') == 0 and file != 'Engine' and not re.search(r'[\\/]', file):
        return 'builtin'
    return 'engine'


def module_path(file):
    """部署路径 .../behavior_packs/<包目录>/<模块路径> → 模块路径；不在包内时返回 None。"""
    parts = [p for p in re.split(r'[\\/]', file or '') if p]
    lowered = [p.lower() for p in parts]
    for marker, skip in (('behavior_packs', 2), ('behavior_pack', 1)):
        if marker in lowered:
            index = len(lowered) - 1 - lowered[::-1].index(marker)
            if index + skip < len(parts):
                return '/'.join(parts[index + skip:])
    return None


def source_roots(project):
    """项目与依赖的行为包目录；解析失败时退回项目内的常规目录，不安装或运行钩子。"""
    if not project:
        return []
    project = Path(project).resolve()
    roots = []
    if (project / 'pyproject.toml').is_file():
        try:
            from ..dependencies import DependencyService, read_project
            manager = DependencyService(project).resolve(read_project(project))
            packs = [getattr(manager.root_node, 'addon_pack', None)] + list(manager.get_all_dependencies().values())
            roots += [Path(p.behavior_pack_dir) for p in packs if p is not None and getattr(p, 'behavior_pack_dir', None)]
        except Exception:
            pass
    roots += [project / 'behavior_pack']
    parent = project / 'behavior_packs'
    roots += sorted(p for p in parent.iterdir() if p.is_dir()) if parent.is_dir() else []
    return [r for r in dict.fromkeys(roots) if r.is_dir()]


class _Sources:
    def __init__(self, project):
        self.project = Path(project).resolve() if project else None
        self.roots = None

    def find(self, module):
        if not module or not self.project:
            return None
        if self.roots is None:
            self.roots = source_roots(self.project)
        for root in self.roots:
            candidate = root / module
            if candidate.is_file():
                try:
                    return str(candidate.relative_to(self.project))
                except ValueError:
                    return str(candidate)
        return None


def _ms(value):
    return round(value / 1e6, 3)


def summarize(raw, project=None, top=15, filter=None):
    zones = raw['zones']
    span = max(raw['capture']['span_ns'], 1) / 1e9
    thread_names = {t['id']: t['name'] for t in raw['threads']}
    sources = _Sources(project)
    kinds = [classify(z) for z in zones]
    modules = [module_path(z['file']) if kind == 'script' else None for z, kind in zip(zones, kinds)]
    callers = {}
    builtin_from_script = 0
    for edge in raw['edges']:
        if edge['parent'] >= 0:
            callers.setdefault(edge['child'], []).append(edge)
            if kinds[edge['child']] == 'builtin' and kinds[edge['parent']] == 'script':
                builtin_from_script += edge['total_ns']

    def label(i):
        z = zones[i]
        if kinds[i] == 'script':
            return '%s (%s:%d)' % (z['name'], modules[i] or z['file'], z['line'])
        return z['name']

    def view(i):
        z = zones[i]
        item = {'name': z['name'], 'kind': kinds[i], 'count': z['count'], 'per_second': round(z['count'] / span, 2),
                'total_ms': _ms(z['total_ns']), 'self_ms': _ms(z['self_ns']),
                'mean_ms': _ms(z['total_ns'] / z['count']) if z['count'] else 0,
                'p50_ms': _ms(z['p50_ns']), 'p95_ms': _ms(z['p95_ns']), 'p99_ms': _ms(z['p99_ns']),
                'max_ms': _ms(z['max_ns'])}
        if kinds[i] == 'script':
            item.update(module=modules[i], line=z['line'], source=sources.find(modules[i]))
            if not modules[i]:
                item['file'] = z['file']
        item['threads'] = [thread_names.get(t['id'], str(t['id']))
                           for t in sorted(z['threads'], key=lambda t: -t['self_ns'])][:3]
        item['callers'] = [label(e['parent']) for e in sorted(callers.get(i, []), key=lambda e: -e['total_ns'])[:3]]
        return item

    def loop(name):
        index = next((i for i, z in enumerate(zones) if z['name'] == name and kinds[i] == 'engine'), None)
        if index is None:
            return None
        z = zones[index]
        return {'zone': name, 'count': z['count'], 'per_second': round(z['count'] / span, 2),
                'mean_ms': _ms(z['total_ns'] / max(z['count'], 1)), 'p50_ms': _ms(z['p50_ns']),
                'p95_ms': _ms(z['p95_ns']), 'p99_ms': _ms(z['p99_ns']), 'max_ms': _ms(z['max_ns'])}

    needle = (filter or '').lower()
    script_ids = [i for i, kind in enumerate(kinds) if kind == 'script' and
                  (not needle or needle in zones[i]['name'].lower() or needle in (modules[i] or zones[i]['file']).lower())]
    script_self = sum(zones[i]['self_ns'] for i, kind in enumerate(kinds) if kind == 'script')
    engine_ids = [i for i, kind in enumerate(kinds) if kind == 'engine']

    windows = []
    for window in raw.get('windows', []):
        slowest = []
        for instance in window['slowest']:
            entries = []
            # 窗口所在线程的条目优先，其他线程（可能只是等待）其次
            ordered = sorted(instance['top_self'], key=lambda e: (e['thread'] != instance['thread'], -e['self_ns']))
            for entry in ordered[:8]:
                i = entry['zone']
                entries.append({'zone': label(i), 'kind': kinds[i], 'thread': thread_names.get(entry['thread'], str(entry['thread'])),
                                'self_ms': _ms(entry['self_ns'])})
            slowest.append({'at_s': round(instance['start_ns'] / 1e9, 3), 'duration_ms': _ms(instance['duration_ns']),
                            'thread': thread_names.get(instance['thread'], str(instance['thread'])), 'top_self': entries})
        windows.append({'zone': window['zone'], 'slowest': slowest})

    return {
        'capture': {'program': raw['capture']['program'], 'span_s': round(span, 3), 'zone_count': raw['capture']['zone_count'],
                    'tracy_version': raw.get('tracy_version')},
        'main_loop': loop(MAIN_LOOP),
        'server_tick': loop(SERVER_TICK),
        'script': {'self_ms_per_s': round(script_self / 1e6 / span, 3),
                   'builtin_from_script_ms_per_s': round(builtin_from_script / 1e6 / span, 3),
                   'functions': sum(1 for kind in kinds if kind == 'script')},
        'scripts': [view(i) for i in sorted(script_ids, key=lambda i: -zones[i]['total_ns'])[:top]],
        'script_spikes': [view(i) for i in sorted(script_ids, key=lambda i: -zones[i]['max_ns'])[:min(top, 8)]],
        'engine': [view(i) for i in sorted(engine_ids, key=lambda i: -zones[i]['self_ns'])[:top]],
        'windows': windows,
    }


def _key(item):
    return (item['kind'], item['name'], item.get('module') or item.get('file'), item.get('line'))


def diff(base, new, top=15):
    """按每秒耗时对比两次摘要（采集时长可以不同）。摘要需使用较大的 top 生成以覆盖足够函数。"""
    def rate(item, summary):
        return item['total_ms'] / max(summary['capture']['span_s'], 1e-9)

    def compare(section):
        before = {_key(item): item for item in base[section]}
        after = {_key(item): item for item in new[section]}
        rows = []
        for key in dict.fromkeys(list(before) + list(after)):
            a, b = before.get(key), after.get(key)
            ref = b or a
            row = {'name': ref['name'], 'kind': ref['kind'],
                   'base_ms_per_s': round(rate(a, base), 3) if a else None,
                   'new_ms_per_s': round(rate(b, new), 3) if b else None,
                   'base_mean_ms': a['mean_ms'] if a else None, 'new_mean_ms': b['mean_ms'] if b else None,
                   'base_max_ms': a['max_ms'] if a else None, 'new_max_ms': b['max_ms'] if b else None}
            if ref.get('module') or ref.get('line') is not None:
                row.update(module=ref.get('module'), line=ref.get('line'))
            row['delta_ms_per_s'] = round((row['new_ms_per_s'] or 0) - (row['base_ms_per_s'] or 0), 3)
            rows.append(row)
        return sorted(rows, key=lambda r: -abs(r['delta_ms_per_s']))[:top]

    def loop(name):
        a, b = base.get(name), new.get(name)
        if not a or not b:
            return None
        return {k: {'base': a[k], 'new': b[k], 'delta': round(b[k] - a[k], 3)}
                for k in ('mean_ms', 'p50_ms', 'p95_ms', 'p99_ms', 'max_ms', 'per_second')}

    return {'main_loop': loop('main_loop'), 'server_tick': loop('server_tick'),
            'script_self_ms_per_s': {'base': base['script']['self_ms_per_s'], 'new': new['script']['self_ms_per_s'],
                                     'delta': round(new['script']['self_ms_per_s'] - base['script']['self_ms_per_s'], 3)},
            'scripts': compare('scripts'), 'engine': compare('engine')}


def _where(item):
    if item['kind'] != 'script':
        return ''
    return '%s:%s' % (item.get('source') or item.get('module') or item.get('file'), item.get('line'))


def format_summary(summary):
    lines = []
    capture = summary['capture']
    lines.append('采集 %.1f 秒 · %s 个区段 · %s' % (capture['span_s'], format(capture['zone_count'], ','), capture['program']))
    for key, title in (('main_loop', '主循环'), ('server_tick', '服务端更新')):
        loop = summary.get(key)
        if loop:
            lines.append('%s %s：p50 %.2fms  p95 %.2fms  p99 %.2fms  最大 %.2fms  （%.1f 次/秒）' % (
                title, loop['zone'], loop['p50_ms'], loop['p95_ms'], loop['p99_ms'], loop['max_ms'], loop['per_second']))
    script = summary['script']
    lines.append('脚本：自身 %.2f ms/秒，脚本调用的内置函数 %.2f ms/秒，%d 个函数' % (
        script['self_ms_per_s'], script['builtin_from_script_ms_per_s'], script['functions']))
    span = max(capture['span_s'], 1e-9)

    def table(title, items):
        if not items:
            return
        lines.append('')
        lines.append(title)
        lines.append('  %9s %9s %8s %8s %8s %8s  %s' % ('总ms/秒', '自身ms/秒', '平均ms', 'p95ms', '最大ms', '次/秒', '函数'))
        for item in items:
            lines.append('  %9.2f %9.2f %8.3f %8.3f %8.2f %8.1f  %s %s' % (
                item['total_ms'] / span, item['self_ms'] / span, item['mean_ms'], item['p95_ms'], item['max_ms'],
                item['per_second'], item['name'], _where(item)))

    table('脚本函数（按总耗时）', summary['scripts'])
    table('脚本耗时尖峰（按单次最大）', summary['script_spikes'])
    table('引擎区段（按自身耗时）', summary['engine'])
    for window in summary['windows']:
        if not window['slowest']:
            continue
        lines.append('')
        lines.append('最慢的 %s：' % window['zone'])
        for instance in window['slowest']:
            parts = ['%s[%s] %.1f' % (e['zone'], e['thread'], e['self_ms']) for e in instance['top_self'][:5]]
            lines.append('  %.2fms @%.2fs  %s' % (instance['duration_ms'], instance['at_s'], '；'.join(parts)))
    return '\n'.join(lines)


def format_diff(result):
    lines = []
    for key, title in (('main_loop', '主循环'), ('server_tick', '服务端更新')):
        loop = result.get(key)
        if loop:
            lines.append('%s：p50 %.2f→%.2fms  p95 %.2f→%.2fms  最大 %.2f→%.2fms' % (
                title, loop['p50_ms']['base'], loop['p50_ms']['new'], loop['p95_ms']['base'], loop['p95_ms']['new'],
                loop['max_ms']['base'], loop['max_ms']['new']))
    s = result['script_self_ms_per_s']
    lines.append('脚本自身：%.2f → %.2f ms/秒（%+.2f）' % (s['base'], s['new'], s['delta']))
    for section, title in (('scripts', '脚本函数变化'), ('engine', '引擎区段变化')):
        lines.append('')
        lines.append(title + '（按每秒耗时变化）：')
        for row in result[section]:
            where = ' %s:%s' % (row.get('module'), row.get('line')) if row.get('module') else ''
            lines.append('  %+9.2f ms/秒  %s → %s  %s%s' % (
                row['delta_ms_per_s'], '-' if row['base_ms_per_s'] is None else '%.2f' % row['base_ms_per_s'],
                '-' if row['new_ms_per_s'] is None else '%.2f' % row['new_ms_per_s'], row['name'], where))
    return '\n'.join(lines)
