# -*- coding: utf-8 -*-

import os
import shutil
import click

from ..utils.utils import ensure_dir
from .file_merge import try_merge_file

# Python 包管理和其他应该忽略的文件和目录
EXCLUDED_PATTERNS = [
    # Python 包管理
    ".egg-info",
    "__pycache__",
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".eggs",
    ".pytest_cache",
    ".tox",
    ".coverage",
    ".coverage.*",
    "htmlcov",
    # 版本控制
    ".git",
    ".hg",
    ".svn",
    ".bzr",
    # 其他临时文件
    ".DS_Store",
    "Thumbs.db"
]

MANIFEST_FILES = [
    "manifest.json",
    "pack_manifest.json"
]


class AddonsPack(object):

    pkg_name: str
    path: str
    is_origin: bool
    behavior_pack_dir: str
    resource_pack_dir: str

    def __init__(self, pkg_name, path, is_origin=False):
        self.pkg_name = pkg_name
        self.path = path
        self.is_origin = is_origin
        self.behavior_pack_dir = None
        self.resource_pack_dir = None
        # 进入此目录，查找内部的行为包和资源包的路径
        os.chdir(self.path)
        for item in os.listdir(self.path):
            item_path = os.path.join(self.path, item)
            if os.path.isdir(item_path):
                if item.startswith("behavior_pack") or item.startswith("BehaviorPack"):
                    self.behavior_pack_dir = item_path
                elif item.startswith("resource_pack") or item.startswith("ResourcePack"):
                    self.resource_pack_dir = item_path
        if not self.behavior_pack_dir:
            self.behavior_pack_dir = os.path.join(self.path, "behavior_pack")
        if not self.resource_pack_dir:
            self.resource_pack_dir = os.path.join(self.path, "resource_pack")

    def should_exclude(self, path):
        """判断文件或目录是否应该被排除"""
        for pattern in EXCLUDED_PATTERNS:
            if pattern in path:
                return True
        # 得到文件名
        filename = os.path.basename(path)
        if not self.is_origin and filename in MANIFEST_FILES:
            return True
        return False

    def copy_behavior_to(self, target_dir: str):
        """复制行为包和资源包到目标目录"""
        if self.behavior_pack_dir:
            target_path = os.path.join(target_dir, os.path.basename(self.behavior_pack_dir))
            os.makedirs(target_path, exist_ok=True)

            # 使用自定义复制函数而不是shutil.copytree
            for root, dirs, files in os.walk(self.behavior_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not self.should_exclude(os.path.join(root, d))]

                # 计算相对路径
                rel_path = os.path.relpath(root, self.behavior_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_path, rel_path) if rel_path != '.' else target_path
                ensure_dir(target_root)

                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if not self.should_exclude(src_file):
                        dest_file = os.path.join(target_root, file)
                        # 如果是Python文件，检查并添加编码声明
                        if file.endswith('.py'):
                            self._copy_with_encoding_check(src_file, dest_file)
                        else:
                            shutil.copy2(src_file, dest_file)

    def copy_resource_to(self, target_dir: str):
        """复制资源包到目标目录"""
        if self.resource_pack_dir:
            target_path = os.path.join(target_dir, os.path.basename(self.resource_pack_dir))
            os.makedirs(target_path, exist_ok=True)

            # 使用自定义复制函数而不是shutil.copytree
            for root, dirs, files in os.walk(self.resource_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not self.should_exclude(os.path.join(root, d))]

                # 计算相对路径
                rel_path = os.path.relpath(root, self.resource_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_path, rel_path) if rel_path != '.' else target_path
                ensure_dir(target_root)

                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if not self.should_exclude(src_file):
                        dest_file = os.path.join(target_root, file)
                        # 如果是Python文件，检查并添加编码声明
                        if file.endswith('.py'):
                            self._copy_with_encoding_check(src_file, dest_file)
                        else:
                            shutil.copy2(src_file, dest_file)

    def merge_behavior_into(self, target_behavior_dir: str):
        """合并行为包到目标行为包目录"""
        if self.behavior_pack_dir:
            for root, dirs, files in os.walk(self.behavior_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not self.should_exclude(os.path.join(root, d))]

                # 计算相对路径
                rel_path = os.path.relpath(root, self.behavior_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_behavior_dir, rel_path) if rel_path != '.' else target_behavior_dir
                ensure_dir(target_root)

                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if self.should_exclude(src_file):
                        continue

                    dest_file = os.path.join(target_root, file)

                    if file.endswith('.py'):  # 如果是Python文件，直接无脑覆盖
                        self._copy_with_encoding_check(src_file, dest_file)
                    elif os.path.exists(dest_file):  # 如果文件已存在，尝试合并
                        suc, reason = try_merge_file(src_file, dest_file)
                        if not suc:
                            click.secho(f"❌ 未处理的文件冲突: {src_file} -> {dest_file} {reason}", fg="red")
                    else:
                        shutil.copy2(src_file, dest_file)

    def merge_resource_into(self, target_resource_dir: str):
        """合并资源包到目标资源包目录"""
        if self.resource_pack_dir:
            for root, dirs, files in os.walk(self.resource_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not self.should_exclude(os.path.join(root, d))]

                # 计算相对路径
                rel_path = os.path.relpath(root, self.resource_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_resource_dir, rel_path) if rel_path != '.' else target_resource_dir
                ensure_dir(target_root)

                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if self.should_exclude(src_file):
                        continue

                    dest_file = os.path.join(target_root, file)
                    # 处理文件冲突
                    if file.endswith('.py'):
                        self._copy_with_encoding_check(src_file, dest_file)
                    elif os.path.exists(dest_file):
                        suc, reason = try_merge_file(src_file, dest_file)
                        if not suc:
                            click.secho(f"⚠️ 警告: 文件合并异常 {src_file} -> {dest_file} {reason}", fg="yellow")
                            # 如果是Python文件，检查并添加编码声明
                            if file.endswith('.py'):
                                self._copy_with_encoding_check(src_file, dest_file)
                            else:
                                shutil.copy2(src_file, dest_file)
                    else:
                        shutil.copy2(src_file, dest_file)

    def _copy_with_encoding_check(self, src_file, dest_file):
        """复制Python文件，并检查添加编码声明"""
        try:
            with open(src_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查是否有编码声明
            has_coding = False
            first_line = content.splitlines()[0] if content.splitlines() else ""
            if "# -*- coding: utf-8 -*-" in first_line or "# coding: utf-8" in first_line:
                has_coding = True

            # 如果没有编码声明，则添加
            if not has_coding:
                content = "# -*- coding: utf-8 -*-\n" + content

            # 写入目标文件
            with open(dest_file, 'w', encoding='utf-8') as f:
                f.write(content)

            # 复制文件元数据
            shutil.copystat(src_file, dest_file)
        except Exception as e:
            click.secho(f"⚠️ 添加编码声明时出错: {src_file} -> {dest_file}: {str(e)}", fg="yellow")
            # 如果出错，则直接复制
            shutil.copy2(src_file, dest_file)