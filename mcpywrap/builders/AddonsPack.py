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

    def copy_behavior_to(self, target_dir: str, rename: str = None):
        """
        复制行为包和资源包到目标目录
        target_dir为父目录
        """
        if self.behavior_pack_dir:
            target_path = os.path.join(target_dir, os.path.basename(self.behavior_pack_dir) if not rename else rename)
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

    def copy_resource_to(self, target_dir: str, rename: str = None):
        """
        复制资源包到目标目录
        target_dir为父目录
        """
        if self.resource_pack_dir:
            target_path = os.path.join(target_dir, os.path.basename(self.resource_pack_dir) if not rename else rename)
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
                    if not self.should_exclude(src_file):
                        # 计算源文件的相对路径
                        src_rel_path = os.path.relpath(src_file, self.behavior_pack_dir)
                        dest_file = os.path.join(target_root, file)
                        self.merge_behavior_single_file_to(src_rel_path, dest_file)

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
                    if not self.should_exclude(src_file):
                        # 计算源文件的相对路径
                        src_rel_path = os.path.relpath(src_file, self.resource_pack_dir)
                        dest_file = os.path.join(target_root, file)
                        self.merge_resource_single_file_to(src_rel_path, dest_file)

    def merge_behavior_single_file_to(self, src_rel_path: str, dest_abs_path: str):
        """合并行为包单个文件，src为相对路径，dest为绝对路径"""
        if self.behavior_pack_dir:
            src_file = os.path.join(self.behavior_pack_dir, src_rel_path)
            if os.path.exists(src_file):
                self._merge_single_file(src_file, dest_abs_path)
                return True
        return False
    
    def merge_resource_single_file_to(self, src_rel_path: str, dest_abs_path: str):
        """合并资源包单个文件，src为相对路径，dest为绝对路径"""
        if self.resource_pack_dir:
            src_file = os.path.join(self.resource_pack_dir, src_rel_path)
            if os.path.exists(src_file):
                self._merge_single_file(src_file, dest_abs_path)
                return True
        return False
    
    def _merge_single_file(self, src_file: str, dest_file: str):
        """合并单个文件"""
        if os.path.exists(dest_file):
            if self.should_exclude(dest_file):
                return
            # 处理文件冲突
            if src_file.endswith('.py'):
                self._copy_with_encoding_check(src_file, dest_file)
            elif os.path.exists(dest_file):
                suc, reason = try_merge_file(src_file, dest_file)
                if not suc:
                    click.secho(f"⚠️ 警告: 文件合并异常 {src_file} -> {dest_file} {reason}", fg="yellow")
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

    def is_behavior_file(self, file_path):
        """
        判断文件是否为行为包文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 如果是行为包文件返回True
        """
        return "behavior_pack" in file_path.lower() or "behaviorpack" in file_path.lower()
    
    def is_resource_file(self, file_path):
        """
        判断文件是否为资源包文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 如果是资源包文件返回True
        """
        return "resource_pack" in file_path.lower() or "resourcepack" in file_path.lower()
    
    def get_relative_path_in_pack(self, file_path):
        """
        获取文件在包中的相对路径
        
        Args:
            file_path: 文件的绝对路径
            
        Returns:
            tuple: (是否为包文件, 包类型, 相对路径)
                包类型: "behavior" 或 "resource"
                相对路径: 在包中的相对路径，如果不在包中则为None
        """
        # 检查是行为包还是资源包文件
        is_behavior = self.is_behavior_file(file_path)
        is_resource = self.is_resource_file(file_path)
        
        if not (is_behavior or is_resource):
            return False, None, None
            
        # 确定包类型
        pack_type = "behavior" if is_behavior else "resource"
        
        # 计算在包中的相对路径
        parts = file_path.split(os.sep)
        for i, part in enumerate(parts):
            if (is_behavior and ("behavior_pack" in part.lower() or "behaviorpack" in part.lower())) or \
               (is_resource and ("resource_pack" in part.lower() or "resourcepack" in part.lower())):
                if i + 1 < len(parts):
                    rel_path = os.path.join(*parts[i+1:])
                    return True, pack_type, rel_path
                else:
                    return True, pack_type, ""
                
        return False, None, None
