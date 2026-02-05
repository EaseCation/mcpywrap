# -*- coding: utf-8 -*-
"""
打包命令模块
"""
import os
import shutil
import zipfile
import gc
import stat
import time
import click
from ..config import (
    config_exists,
    get_project_name,
    get_project_type,
    get_project_version,
)

from ..builders.project_builder import AddonProjectBuilder, MapProjectBuilder


base_dir: str = os.getcwd()


@click.command()
@click.option("--merge", "-m", is_flag=True, help="强制合并所有资源文件")
def package_cmd(merge):
    """构建并打包可直接用于《我的世界》中国版市场发布的压缩包"""
    if not config_exists():
        click.secho(
            "❌ 错误: 未找到配置文件。请先运行 `mcpywrap init` 初始化项目。", fg="red"
        )
        return False

    project_name: str = get_project_name()
    version: str = get_project_version()

    dist_dir: str = os.path.join(base_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    temp_build_dir: str = os.path.join(dist_dir, f"_temp_build_{project_name}")

    # 预清理旧临时目录,如果存在
    _force_remove(temp_build_dir)
    os.makedirs(temp_build_dir, exist_ok=True)

    project_type: str = get_project_type()

    if project_type == "addon":
        builder = AddonProjectBuilder(base_dir, temp_build_dir)
        success, error = builder.build()
    elif project_type == "map":
        builder = MapProjectBuilder(base_dir, temp_build_dir, merge)
        success, error = builder.build()
    else:
        click.secho("❌ 暂未支持该项目类型", fg="red")
        _force_remove(temp_build_dir)
        return False

    if not success:
        click.secho(f"❌ 构建失败: {error}", fg="bright_red")
        _force_remove(temp_build_dir)
        return False

    zip_name: str = f"{project_name}-{version}.zip"
    zip_path: str = os.path.join(dist_dir, zip_name)

    # Packaging
    zipf = None
    try:
        zipf = zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED)

        if project_type == "addon":
            _zip_dir_keep_empty(
                zipf,
                os.path.join(temp_build_dir, "behavior_pack"),
                f"{project_name}_bp",
            )
            _zip_dir_keep_empty(
                zipf,
                os.path.join(temp_build_dir, "resource_pack"),
                f"{project_name}_rp",
            )

        elif project_type == "map":
            _zip_dir_keep_empty(zipf, temp_build_dir, "")

    finally:
        if zipf is not None:
            zipf.close()

    del zipf
    gc.collect()
    time.sleep(0.2)

    # 避免cwd锁死
    os.chdir(dist_dir)
    gc.collect()
    time.sleep(0.2)

    _force_remove(temp_build_dir)

    click.secho(f"✅ 打包成功！分发文件路径: {zip_path}", fg="green")
    return True


def _zip_dir_keep_empty(zipf: zipfile.ZipFile, src_dir: str, dst_root: str):
    """
    通过递归将目录写入zip文件，并显式保留所有空目录

    该函数用于弥补zipfile模块的默认行为缺陷：
    zipfile默认不会在压缩包中保留空目录。该函数会为每一个遍历到的目录（无论是否包含文件）写入一个
    以 '/' 结尾的ZipInfo条目，从而确保目录结构完整

    Brief:
    - 遍历src_dir下的所有子目录与文件
    - 每个目录都会在zip中创建对应目录项
    - 每个文件都会按相对路径写入zip中
    - 不负责zipf的打开与关闭生命周期

    Args:
        zipf (zipfile.ZipFile):
            已打开的zipfile对象，必须处于写入模式（'w' 或 'a'）

        src_dir (str):
            需要被压缩的源目录路径

        dst_root (str):
            压缩包内的根目录名称：
            - 为空字符串时，src_dir内容直接作为压缩包根目录
            - 非空字符串时，src_dir内容将映射到该目录下

    Returns:
        None
    """

    if not os.path.exists(src_dir):
        return

    for root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, src_dir)
        if rel_root == ".":
            arc_root = dst_root
        else:
            arc_root = os.path.join(dst_root, rel_root) if dst_root else rel_root

        arc_dir = arc_root.rstrip("/") + "/"
        zipf.writestr(zipfile.ZipInfo(arc_dir), "")

        for file in files:
            abs_path = os.path.join(root, file)
            arc_name = os.path.join(arc_root, file) if arc_root else file
            zipf.write(abs_path, arc_name)


def _force_remove(path: str):
    """
    在Windows环境下强制删除目录及其自身

    该函数尝试用于解决Windows下常见的目录移除问题，包括：
    - 文件或目录被标记为只读
    - Python或第三方库仍持有文件句柄
    - shutil.rmtree偶发性失败但未抛出异常？

    函数被设计为清理阶段保险行为，所以不会向外抛出异常

    Args:
        path (str):
            需要被彻底删除文件及其目录本身的路径

    Returns:
        None
    """

    if not os.path.exists(path):
        return

    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for _ in range(5):
        try:
            shutil.rmtree(path, onerror=_onerror)
            if not os.path.exists(path):
                return
        except Exception:
            pass

        gc.collect()
        time.sleep(0.2)

    try:
        for root, dirs, files in os.walk(path, topdown=False):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                except Exception:
                    pass
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except Exception:
                    pass
        os.rmdir(path)
    except Exception:
        pass
