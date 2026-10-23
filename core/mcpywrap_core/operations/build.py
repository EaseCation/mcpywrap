"""Shared build pipeline, including preparation and project hooks."""
import os
from pathlib import Path
import click
from ..config import ensure_map_setuptools_sync, get_mcpywrap_config
from ..builders.project_builder import AddonProjectBuilder, MapProjectBuilder


def build_project(source, merge=False, *, preparation_event='before_build'):
    source = Path(source).resolve()
    ensure_map_setuptools_sync(interactive=False)
    target = get_mcpywrap_config().get('target_dir')
    if not target:
        raise ValueError('缺少 target_dir，请设置 tool.mcpywrap.target_dir')
    target = os.path.normpath(os.path.join(str(source), target))
    from ..project_scripts import before, configured, validate_build
    from ..consumer_prepare import PreparationPlan
    plan = PreparationPlan(source)
    if configured(source):
        validate_build(source, target, resolved=plan.manager)
    with before(source, preparation_event, plan=plan) as scripts:
        if not build(str(source), target, force_merge=merge, raise_errors=True, resolved=plan.manager, report=False):
            raise ValueError('构建失败')
    sources = {}
    if plan.manager is not None:
        root = plan.manager.root_node.addon_pack
        sources = {kind: str(Path(directory).relative_to(source))
                   for kind in ('behavior', 'resource')
                   if (directory := getattr(root, kind + '_pack_dir', None))}
    return {'output': target, 'source_packs': sources, **({'scripts': scripts} if scripts else {})}


def build(source_dir, target_dir, force_merge: bool = False, raise_errors=False, *, resolved=None, report=True):
    """
    执行项目构建

    Args:
        source_dir: 源代码目录
        target_dir: 目标目录
        force_merge: 是否强制合并资源文件

    Returns:
        bool: 是否构建成功
    """
    if target_dir is None:
        click.secho('❌ 错误: 未指定目标目录。', fg="red")
        return False

    from ..dependencies import read_project
    project_type = read_project(source_dir).get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')


    if project_type == "addon":
        builder = AddonProjectBuilder(source_dir, target_dir, resolved=resolved)
        success, error = builder.build()
    elif project_type == "map":
        builder = MapProjectBuilder(source_dir, target_dir, force_merge)
        success, error = builder.build()
    else:
        click.secho('❌ 暂未支持: 当前仅支持Addons和Map项目的构建', fg="red")
        return False

    if success:
        if report:
            click.secho('✅ 构建成功！项目已生成到目标目录。', fg="green")
        return True
    else:
        if raise_errors:
            raise ValueError(f'构建失败: {error}')
        click.secho(f'❌ 构建失败: ', fg="red", nl=False)
        click.secho(f'{error}', fg="bright_red")
        return False
