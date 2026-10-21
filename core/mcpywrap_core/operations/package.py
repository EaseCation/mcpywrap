"""One packaging pipeline for every frontend; no platform-specific assembly."""
import os
import tempfile
import zipfile
from pathlib import Path
from ..dependencies import DependencyError, read_project
from ..builders.project_builder import AddonProjectBuilder, MapProjectBuilder
from ..utils.paths import is_link


def package_project(source, merge=False):
    # 每次调用读取当前项目，避免 CLI 导入时的工作目录影响打包位置。
    source = Path(source).resolve()
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

        from ..project_scripts import before, configured, validate_build, operation
        from ..consumer_prepare import PreparationPlan
        plan = PreparationPlan(source)
        if configured(source):
            validate_build(source, source/'dist'/'_script_preflight', resolved=plan.manager)
        with before(source, 'before_package', plan=plan) as scripts:
            dist = source / 'dist'
            dist.mkdir(exist_ok=True)
            destination = dist / f'{name}-{version}.zip'
            # 临时构建与 ZIP 独立于现有产物，全部成功后才替换同版本分发包。
            with tempfile.TemporaryDirectory(prefix='_temp_package_', dir=dist) as temporary:
                output = Path(temporary) / 'build'
                builder = (AddonProjectBuilder(source, output, resolved=plan.manager) if project_type == 'addon'
                           else MapProjectBuilder(source, output, merge))
                success, error = builder.build()
                if not success:
                    raise ValueError(f'构建失败: {error}')
                # 依赖组装完成后，仅将隔离副本提供给压缩前处理器。
                identity = _package_manifests(output)
                with operation(source, 'before_archive', lock_held=True, after_task=plan.check,
                               package_root=output) as finalizers:
                    scripts.extend(finalizers)
                if identity != _package_manifests(output):
                    raise ValueError('压缩前处理不得修改包 manifest 或包身份')
                if any(is_link(p) for p in output.rglob('*')):
                    raise ValueError('压缩前处理不能在产物中引入目录或文件链接')
                archive = Path(temporary) / 'package.zip'
                with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    if project_type == 'addon':
                        # 新构建器保留源包目录名；分发包仍遵循 PR 的 name_bp/name_rp 约定。
                        for kind, suffix in (('behavior', 'bp'), ('resource', 'rp')):
                            folder = getattr(builder.target_addon, kind + '_pack_dir')
                            # 网易上传错误码24检查行为包entities目录；纯脚本Addon也保留
                            # 空目录条目，不创建虚构实体，不修改项目源码或外层包名。
                            if kind == 'behavior' and folder and Path(folder).is_dir():
                                (Path(folder) / 'entities').mkdir(exist_ok=True)
                            _zip_dir_keep_empty(zipf, folder, f'{name}_{suffix}')
                    else:
                        _zip_dir_keep_empty(zipf, output, '')
                os.replace(archive, destination)
    except (OSError, ValueError) as exc:
        from ..project_scripts import ScriptError
        from ..host import CapabilityUnavailable
        if isinstance(exc, (ScriptError, CapabilityUnavailable)):
            raise
        label = '构建失败' if isinstance(exc, DependencyError) else '打包失败'
        raise ValueError(f'{label}: {exc}') from exc

    return {'artifact': str(destination), **({'scripts': scripts} if scripts else {})}


def _package_manifests(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and p.name in ('manifest.json', 'pack_manifest.json')}


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
