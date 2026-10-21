# coding: utf-8
"""从控件路径与真实文字生成浅层语义布局；不改变输入目标与校验。"""
import re

try:
    _outline_text = unicode
except NameError:
    _outline_text = str


def _under(path, parent):
    return path == parent or path.startswith(parent.rstrip('/') + '/')


def _parent(path):
    return path.rsplit('/', 1)[0]


def _common(paths):
    if not paths:
        return ''
    parts = paths[0].split('/')
    for path in paths[1:]:
        other = path.split('/')
        i = 0
        while i < min(len(parts), len(other)) and parts[i] == other[i]:
            i += 1
        parts = parts[:i]
    return '/'.join(parts)


def _ancestors(path):
    while '/' in path:
        path = _parent(path)
        if path:
            yield path


def _box(rows):
    return (min(r['bounds'][0] for r in rows), min(r['bounds'][1] for r in rows),
            max(r['bounds'][2] for r in rows), max(r['bounds'][3] for r in rows))


def _order(row):
    # 同一行按左右阅读。轻微文本基线差异不拆成不同的行。
    return (round(row['bounds'][1] / 4.), row['bounds'][0], row['path'])


def _heading_hint(path):
    return bool(re.search(r'(?:title|heading|header|group_label|preferences_label|options_label)', path.lower()))


def _field_prefix(path):
    if '/option_generic_core/' in path:
        return path.rsplit('/option_generic_core/', 1)[0] + '/option_generic_core'
    for prefix in _ancestors(path):
        name = prefix.rsplit('/', 1)[-1].lower()
        if _heading_hint(name):
            continue
        if re.search(r'(?:^|[_.-])(?:row|field|option|entry)(?:[_.-]|\d|$)', name):
            return prefix
    return None


def _fallback_name(path):
    for part in reversed(path.split('/')):
        if part and not re.match(r'^(?:button|panel|control|label|text|content|main|root|default|hover|pressed|button_panel|button_content|centering_panel|clipper_panel)[_\d]*$', part):
            return part[:96]
    return '未命名控件'


def _caption_candidates(rows):
    """关联优先使用共同局部容器；几何只作限制，不跨列猜标签。"""
    controls = [r for r in rows if r['role'] not in ('label', 'scroll')]
    index = {}
    for row in rows:
        for prefix in _ancestors(row['path']):
            index.setdefault(prefix, []).append(row)
    owners, descriptions = {}, {}
    for label in [r for r in rows if r['role'] == 'label']:
        path = label['path']
        direct = [c for c in controls if _under(path, c['path'])]
        owner = max(direct, key=lambda c: len(c['path'])) if direct else None
        if owner is None and not _heading_hint(path):
            for prefix in _ancestors(path):
                members = index.get(prefix, [])
                if any(r['role'] == 'scroll' for r in members):
                    break
                candidates = [c for c in members if c['role'] not in ('label', 'scroll')]
                if len(candidates) != 1:
                    if len(candidates) > 1:
                        break
                    continue
                c = candidates[0]
                box = _box(members)
                height = box[3] - box[1]
                # 整个单按钮对话框的说明不应被吞进按钮名称。
                short_group = len(members) <= 6 and height <= max(64., (c['bounds'][3]-c['bounds'][1])*2.5)
                aligned = min(label['bounds'][2], c['bounds'][2]) > max(label['bounds'][0], c['bounds'][0])
                same_line = min(label['bounds'][3], c['bounds'][3]) > max(label['bounds'][1], c['bounds'][1])
                explicit = _field_prefix(path) == _field_prefix(c['path']) and _field_prefix(path) is not None
                if (explicit or short_group) and (aligned or same_line):
                    owner = c
                break
        if owner is not None:
            text = label.get('text', label['name'])
            owners[path] = owner['path']
            if text not in (owner['name'], _outline_text(owner.get('value', ''))) and text not in owner['name']:
                descriptions.setdefault(owner['path'], []).append(text)
    return owners, descriptions


def prepare_ui_outline(source_rows):
    """输出分组模型。布局包装不成为节点，区域最多一级，小组最多一级。"""
    rows = [dict(row) for row in source_rows]
    owners, descriptions = _caption_candidates(rows)
    by_path = {r['path']: r for r in rows}
    # 已有控件名来自可靠标签时保留；泛化控件名用局部标题补充。
    for path, owner in owners.items():
        control, label = by_path[owner], by_path[path]
        text = label.get('text', label['name'])
        if (control['name'] == control['path'].rsplit('/', 1)[-1] and
                not _under(path, owner) and not text.isdigit()):
            control['name'] = text
    for path, texts in descriptions.items():
        extras = []
        for text in texts:
            if text != by_path[path]['name'] and text not in extras:
                extras.append(text)
        if extras:
            by_path[path]['description'] = ' / '.join(extras)[:256]
    consumed = set(owners)
    # 原生只读字段（如下拉框的标题/当前值）也按“字段: 值”表达。
    fields = {}
    for row in rows:
        prefix = _field_prefix(row['path'])
        if prefix:
            fields.setdefault(prefix, []).append(row)
            row['_field'] = prefix
    for prefix, members in fields.items():
        if any(r['role'] != 'label' for r in members):
            continue
        labels = sorted([r for r in members if r['path'] not in consumed], key=_order)
        if not 2 <= len(labels) <= 3 or any(r.get('ambiguous') for r in labels):
            continue
        caption = labels[0]
        values = labels[1:]
        if not all(r['in_view'] == caption['in_view'] for r in values):
            continue
        caption['value'] = ' / '.join(r.get('text', r['name']) for r in values)
        caption['related_paths'] = [r['path'] for r in values]
        caption['readonly_field'] = True
        consumed.update(r['path'] for r in values)
    meaningful = [r for r in rows if r['path'] not in consumed]
    for row in meaningful:
        if row['role'] != 'label' and row['name'] == row['path'].rsplit('/', 1)[-1]:
            row['name'] = _fallback_name(row['path'])
    groups, membership, headers = [], {}, {}

    def group(name, role, parent=None, anchor=None, prefix=None):
        item = {'id': 'g' + str(len(groups)+1), 'name': name[:128], 'role': role,
                'parent': parent, 'depth': 1 if parent is None else 2,
                '_anchor': anchor, '_prefix': prefix}
        groups.append(item)
        if anchor:
            headers[anchor] = item['id']
        return item

    # 最接近当前视口的滚动容器构成主要区域，嵌套滚动不会无限加深。
    scrolls = sorted([r for r in meaningful if r['role'] == 'scroll'], key=lambda r: len(r['path']))
    regions = []
    for row in scrolls:
        outer = next((g for g in regions if _under(row['path'], g['_prefix'])), None)
        if outer:
            membership[row['path']] = outer['id']
            continue
        prefix = row['path']
        name = '滚动区域'
        if any(s in prefix.lower() for s in ('selector_area', 'navigation', '/nav/')):
            name = '导航'
        elif '/content_area/' in prefix:
            name = '内容'
        item = group(name, 'region', anchor=prefix, prefix=prefix)
        item['_bounds'] = row['bounds']
        regions.append(item)
    for row in meaningful:
        candidates = [g for g in regions if _under(row['path'], g['_prefix'])]
        if candidates:
            membership[row['path']] = candidates[0]['id']

    # 顶部、外置区域标题用空间对齐关联；不把滚动内容第一行误认作区域标题。
    titles = [r for r in meaningful if r['role'] == 'label' and r['path'] not in membership and
              _heading_hint(r['path']) and r['in_view'] and not r.get('_field')]
    title = '当前界面'
    primary = next((r for r in titles if any(s in r['path'].lower() for s in ('dialog_title', 'screen_title', 'page_title'))), None)
    if primary is not None:
        title = primary['name']
        primary['_page_title'] = True
    for heading in titles:
        if heading is primary:
            continue
        candidates = []
        for region in regions:
            b, h = region['_bounds'], heading['bounds']
            overlap = min(b[2], h[2])-max(b[0], h[0])
            if 0 <= b[1]-h[3] <= 48 and overlap > 0 and overlap >= (h[2]-h[0])*.5:
                candidates.append(region)
        if len(candidates) == 1:
            chosen = candidates[0]
            chosen['name'] = heading['name'][:128]
            heading['_region_title'] = chosen['id']

    # 非滚动界面：只在真实分叉形成多个局部面板时保留区域。
    outside = [r for r in meaningful if r['path'] not in membership and not r.get('_page_title') and
               not r.get('_region_title') and r['path'] not in headers]
    common = _common([r['path'] for r in outside])
    branches = {}
    for row in outside:
        rest = row['path'][len(common):].strip('/')
        if rest:
            branch = common + '/' + rest.split('/')[0]
            branches.setdefault(branch, []).append(row)
    candidates = [(p, rs) for p, rs in branches.items() if len(rs) >= 2 and
                  any(r['role'] != 'label' for r in rs)]
    if len(candidates) >= 2:
        for prefix, members in sorted(candidates, key=lambda pair: _order(min(pair[1], key=_order))):
            labels = [r for r in members if r['role'] == 'label' and not r.get('_field') and
                      r['bounds'][1] <= min(c['bounds'][1] for c in members if c['role'] != 'label')]
            heading = min(labels, key=_order) if labels else None
            region = group(heading['name'] if heading else '区域', 'region',
                           anchor=heading['path'] if heading else None, prefix=prefix)
            region['_bounds'] = _box(members)
            regions.append(region)
            for row in members:
                membership[row['path']] = region['id']

    loose = [r for r in outside if r['path'] not in membership]
    if regions and sum(r['role']!='label' for r in loose) >= 2:
        bounds = _box(loose)
        separated = all(min(bounds[2],g['_bounds'][2]) <= max(bounds[0],g['_bounds'][0]) or
                        min(bounds[3],g['_bounds'][3]) <= max(bounds[1],g['_bounds'][1]) for g in regions)
        if separated:
            name = '操作' if all(r['role']=='button' for r in loose) else '内容'
            region = group(name,'region',prefix=_common([r['path'] for r in loose]))
            region['_bounds'] = bounds
            regions.append(region)
            for row in loose:
                membership[row['path']] = region['id']

    if primary is None:
        remaining_titles = [r for r in titles if r['path'] not in membership and
                            r['path'] not in headers and not r.get('_region_title') and
                            re.search(r'(?:title|header)',r['path'].lower())]
        if remaining_titles:
            primary = min(remaining_titles,key=_order)
            title = primary['name']
            primary['_page_title'] = True

    # 区域内按实际标题分段；标题的共同父容器限制作用范围，几何只决定前后。
    root_region = {'id':None, '_prefix':_common([r['path'] for r in meaningful])}
    for region in regions + [root_region]:
        members = [r for r in meaningful if membership.get(r['path']) == region['id'] and r['path'] not in headers
                   and not r.get('_page_title') and not r.get('_region_title')]
        section_labels = []
        for row in members:
            if row['role'] != 'label' or row.get('_field') or row.get('readonly_field') or row.get('ambiguous'):
                continue
            text = row.get('text', row['name'])
            if not text or len(text) > 80 or not re.search(r'[^\W\d_]', text, re.UNICODE):
                continue
            after = [r for r in members if r['path'] != row['path'] and r['bounds'][1] >= row['bounds'][3]-1]
            # 无明确标题提示时，至少要有两个后续交互元素支持分组。
            if not _heading_hint(row['path']) and sum(r['role'] != 'label' for r in after) < 2:
                continue
            if not after:
                continue
            # 位于控件内部的残余文字不是分组标题。
            if any(_under(row['path'], c['path']) for c in members if c['role'] not in ('label','scroll')):
                continue
            section_labels.append(row)
        for heading in sorted(section_labels, key=_order):
            # 丢掉 text/label 包装层，直到该祖先拥有后续兄弟内容。
            scope = _parent(heading['path'])
            while scope and scope != region['_prefix']:
                peers = [r for r in members if r['path'] != heading['path'] and _under(r['path'], scope)]
                if peers:
                    break
                scope = _parent(scope)
            followers = [r for r in members if r['path'] != heading['path'] and _under(r['path'], scope) and
                         r['bounds'][1] >= heading['bounds'][3]-1]
            stops = [h for h in section_labels if h['path'] != heading['path'] and _under(h['path'], scope) and
                     h['bounds'][1] > heading['bounds'][1]+1]
            if stops:
                bottom = min(h['bounds'][1] for h in stops)
                followers = [r for r in followers if r['bounds'][1] < bottom]
            if not followers:
                continue
            section = group(heading['name'], 'section', parent=region['id'], anchor=heading['path'], prefix=scope)
            section['_bounds'] = _box([heading] + followers)
            for row in followers:
                if row['path'] not in headers:
                    membership[row['path']] = section['id']

    group_map = {g['id']: g for g in groups}
    for row in meaningful:
        header = headers.get(row['path'])
        if header and row['role'] == 'scroll':
            row['name'] = group_map[header]['name']
        row['outline_group'] = header
        row['outline_parent'] = group_map[header]['parent'] if header else membership.get(row['path'])
        if row.get('_region_title'):
            row['outline_parent'] = None
        row['outline_depth'] = (group_map[header]['depth'] if header else
                                group_map[row['outline_parent']]['depth']+1 if row['outline_parent'] else 1)
        chain, parent = [], row['outline_parent']
        while parent:
            chain.append(group_map[parent]['name'])
            parent = group_map[parent]['parent']
        row['outline_context'] = list(reversed(chain))

    # 先区域，再区域内的标题/控件，确保树和列表具有相同的阅读顺序。
    ordered = []
    def emit(parent):
        items = []
        siblings = [g for g in groups if g['parent'] == parent]
        # 并排区域按列阅读，即使左侧菜单位于大图标下方，也不先读右侧列表。
        bands = []
        for group_item in siblings:
            bounds = group_item.get('_bounds')
            if bounds is None:
                anchor = by_path.get(group_item['_anchor'])
                bounds = anchor['bounds'] if anchor else (0,0,0,0)
            bands.append([bounds[1],bounds[3],[group_item['id']]])
        merged = True
        while merged:
            merged = False
            for i in range(len(bands)):
                for j in range(i+1,len(bands)):
                    if min(bands[i][1],bands[j][1]) > max(bands[i][0],bands[j][0]):
                        bands[i] = [min(bands[i][0],bands[j][0]),max(bands[i][1],bands[j][1]),bands[i][2]+bands[j][2]]
                        bands.pop(j);merged=True;break
                if merged:break
        band_top = {key:band[0] for band in bands for key in band[2]}
        for g in groups:
            if g['parent'] == parent:
                anchor = by_path.get(g['_anchor'])
                bounds = g.get('_bounds') or (anchor['bounds'] if anchor else (0,0,0,0))
                items.append((band_top[g['id']], bounds[0], '%012.3f'%bounds[1]+g['id'], 'group', g))
        for row in meaningful:
            if row['outline_parent'] == parent and not row['outline_group']:
                items.append((row['bounds'][1], row['bounds'][0], row['path'], 'row', row))
        for _, _, _, kind, item in sorted(items, key=lambda x: (round(x[0]/4.),x[1],x[2])):
            if kind == 'row':
                ordered.append(item)
            else:
                anchor = next((r for r in meaningful if r['path'] == item['_anchor']), None)
                if anchor is not None:
                    ordered.append(anchor)
                emit(item['id'])
    emit(None)
    return {'title': title, 'rows': ordered, 'groups': groups}


def render_ui_outline(model, records, row_by_id):
    """筛选/分页后重建必要祖先；上下文分组不伪造可操作编号。"""
    groups = {g['id']: g for g in model['groups']}
    needed, anchors = set(), {}
    for record in records:
        row = row_by_id[record['id']]
        if row['outline_group']:
            anchors[row['outline_group']] = record
            needed.add(row['outline_group'])
        parent = row['outline_group'] or row['outline_parent']
        while parent:
            needed.add(parent)
            parent = groups[parent]['parent']
    public_groups = []
    for group in model['groups']:
        if group['id'] in needed:
            public_groups.append({k:group[k] for k in ('id','name','role','parent','depth')})
            public_groups[-1]['node_id'] = anchors.get(group['id'],{}).get('id')
            public_groups[-1]['context_only'] = group['id'] not in anchors
    lines = [model['title']]
    rendered_groups = set()

    def line(record, name=None):
        text = '[{0}] {1} {2}'.format(record['id'], record['role'], name or record['name'])
        if 'value' in record:
            value = record['value']
            if record['role'] == 'toggle':
                text += ' [选中]' if value else ' [未选中]'
            else:
                text += ' = ' + _outline_text(value) + ('%' if record['role']=='scroll' else '')
        if record.get('description'):
            text += ' — ' + record['description']
        if not record['in_view']:
            text += ' [offscreen]'
        if record.get('ambiguous'):
            text += ' [ambiguous]'
        return text

    def emit_group(group_id):
        if not group_id or group_id in rendered_groups:
            return
        group = groups[group_id]
        emit_group(group['parent'])
        anchor = anchors.get(group_id)
        text = ('[{0}] {1}'.format(anchor['id'],group['name']) if anchor and anchor['role']=='label'
                else line(anchor,group['name']) if anchor else group['name'])
        lines.append('  '*group['depth'] + text)
        rendered_groups.add(group_id)

    for record in records:
        row = row_by_id[record['id']]
        if row.get('_page_title'):
            continue
        if row.get('_region_title') and row['_region_title'] in needed:
            continue
        emit_group(row['outline_parent'])
        if row['outline_group']:
            emit_group(row['outline_group'])
        else:
            lines.append('  '*row['outline_depth'] + line(record))
    return '\n'.join(lines), public_groups
