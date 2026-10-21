# -*- coding: utf-8 -*-
import os, shutil
from setuptools.command.install import install as _install
from setuptools.command.develop import develop as _develop

def copy_all_content(src, dst, ignore=None):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)

class InstallWithMcwrap(_install):
    def run(self):
        _install.run(self)
        project_name = self.distribution.get_name()
        install_lib = self.install_lib
        target_dir = os.path.join(install_lib, "mcwrap", project_name)
        source_dir = os.path.abspath(os.path.dirname(__file__))
        ignore_patterns = shutil.ignore_patterns("build", "dist", "*.egg-info", ".git", "__pycache__")
        try:
            copy_all_content(source_dir, target_dir, ignore=ignore_patterns)
            print(f"[mcpywrap] 已将项目内容复制到：{target_dir}")
        except Exception as e:
            print("[mcpywrap] 复制项目内容时出错：", e)

class DevelopWithMcwrap(_develop):
    def run(self):
        _develop.run(self)
        project_name = self.distribution.get_name()
        install_dir = getattr(self, 'install_dir', os.path.abspath(os.path.dirname(__file__)))
        target_dir = os.path.join(install_dir, "mcwrap", project_name)
        source_dir = os.path.abspath(os.path.dirname(__file__))
        try:
            if os.path.exists(target_dir):
                if os.path.islink(target_dir):
                    os.unlink(target_dir)
                else:
                    shutil.rmtree(target_dir)
            os.symlink(source_dir, target_dir)
            print(f"[mcpywrap] 已创建符号链接：{target_dir} -> {source_dir}")
        except Exception as e:
            print("[mcpywrap] 创建符号链接时出错：", e)