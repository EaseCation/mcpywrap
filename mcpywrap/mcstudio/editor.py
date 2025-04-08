# -*- coding: utf-8 -*-

import click
import os
import subprocess

from ..config import config_exists, read_config, get_project_dependencies, get_project_type, get_project_name
from ..mcstudio.mcs import *
from .SimpleMonitor import SimpleMonitor


def open_editor(config_path):

    # 获取MC Studio安装目录
    mcs_download_dir = get_mcs_download_path()
    if not mcs_download_dir:
        click.echo(click.style('❌ 未找到MC Studio下载目录，请确保已安装MC Studio', fg='red', bold=True))
        return

    editor_exe = os.path.join(mcs_download_dir, "MCX64Editor", "MC_Editor.exe")
    if not os.path.exists(editor_exe):
        click.echo(click.style('❌ 未找到MC Studio编辑器，请确保已安装MC Studio', fg='red', bold=True))
        return
    
    cmd_str = f'cmd /c start "MC Studio Editor" "{editor_exe}" "{os.path.abspath(config_path)}"'
    proc = subprocess.Popen(cmd_str, shell=True)
    
    return SimpleMonitor("MC_Editor.exe")