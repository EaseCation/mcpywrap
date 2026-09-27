"""构建项目并生成市场分发 ZIP。"""
import os
import tempfile
import zipfile
from pathlib import Path

import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project

from ..config import config_exists
from ..dependencies import read_project
from ..builders.project_builder import AddonProjectBuilder, MapProjectBuilder


@click.command(cls=OperationCommand)
@click.option('--merge', '-m', is_flag=True, help='强制合并所有资源文件（仅地图项目）')
def package_cmd(merge):
    """构建并打包可直接用于《我的世界》中国版市场发布的压缩包。"""
    if not config_exists():
        raise click.ClickException('未找到配置文件。请先运行 `mcpy init` 初始化项目。')

    # 每次调用读取当前项目，避免 CLI 导入时的工作目录影响打包位置。
    source = current_project()
    try:
        config = read_project(source)
        project = config.get('project', {})
        name = project.get('name', 'project')
        version = project.get('version', '0.1.0')
        for label, value in (('name', name), ('version', version)):
            if (not isinstance(value, str) or not value.strip()
                    or any(char in value for char in '/\\:*?"<>|')
                    or any(ord(char) < 32 for char in value)):
                raise ValueError(f'project.{label} 必须是有效的文件名组成部分')
        project_type = config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')
        if project_type not in ('addon', 'map'):
            raise ValueError('当前仅支持 Addon 和 Map 项目的打包')

        dist = source / 'dist'
        dist.mkdir(exist_ok=True)
        destination = dist / f'{name}-{version}.zip'
        # 临时构建与 ZIP 独立于现有产物，全部成功后才替换同版本分发包。
        with tempfile.TemporaryDirectory(prefix='_temp_package_', dir=dist) as temporary:
            output = Path(temporary) / 'build'
            builder = (AddonProjectBuilder(source, output) if project_type == 'addon'
                       else MapProjectBuilder(source, output, merge))
            success, error = builder.build()
            if not success:
                raise click.ClickException(f'构建失败: {error}')
            archive = Path(temporary) / 'package.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if project_type == 'addon':
                    # 新构建器保留源包目录名；分发包仍遵循 PR 的 name_bp/name_rp 约定。
                    for kind, suffix in (('behavior', 'bp'), ('resource', 'rp')):
                        folder = getattr(builder.target_addon, kind + '_pack_dir')
                        _zip_dir_keep_empty(zipf, folder, f'{name}_{suffix}')
                else:
                    _zip_dir_keep_empty(zipf, output, '')
            os.replace(archive, destination)
    except (OSError, ValueError) as exc:
        raise click.ClickException(f'打包失败: {exc}') from exc

    click.secho(f'✅ 打包成功！分发文件路径: {destination}', fg='green')
    return {'artifact': str(destination)}


def _zip_dir_keep_empty(zipf, src_dir, dst_root):
    """保留构建产物的空目录，ZIP 路径统一使用相对路径和正斜杠。"""
    source = Path(src_dir)
    if not source.is_dir():
        return
    for root, dirs, files in os.walk(source):
        dirs.sort()
        relative = Path(root).relative_to(source).as_posix()
        arc_root = '/'.join(part for part in (dst_root, relative if relative != '.' else '') if part)
        if arc_root:
            zipf.writestr(arc_root + '/', '')
        for filename in sorted(files):
            arc_name = f'{arc_root}/{filename}' if arc_root else filename
            zipf.write(Path(root) / filename, arc_name)
