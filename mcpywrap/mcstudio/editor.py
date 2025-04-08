# -*- coding: utf-8 -*-

import click
import os
import subprocess

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

def create_editor_config(project_name: str, project_dir: str, is_map: bool, addon_paths: list[str]):
    download_path = get_mcs_download_path()
    if not download_path:
        click.echo(click.style('❌ 未找到MC Studio下载目录，请确保已安装MC Studio', fg='red', bold=True))
        return
    engine_install_dir = get_mcs_install_location()
    if not engine_install_dir:
        click.echo(click.style('❌ 未找到MC Studio安装目录，请确保已安装MC Studio', fg='red', bold=True))
        return
    engine_versions = get_mcs_game_engine_dirs()
    if not engine_versions:
        click.echo(click.style('❌ 未找到MC Studio游戏引擎目录，请确保已安装MC Studio', fg='red', bold=True))
        return
    engine_version = engine_versions[0]  # 默认使用最新版本
    config = {
        "AssertCacheDir": os.path.join(download_path, "EngineAssert"),
        "CanPublishResourceComponent": True,
        "CodeEnable": True,
        "CreateNew": False,
        "CreateVersion": engine_version,
        "DCWebUrl": "https://x19apigatewayexpr.nie.netease.com",
        "EditAddOnPaths": addon_paths,
        "EditLogFilePath": os.path.join(download_path, "work", "editor", "edit.log"),
        "EditMaterialPaths": [],
        "EditName": project_name,
        "EditVersion": engine_version,
        "EditorResourcePackPath": os.path.join(engine_install_dir, "data", "inner_res"),
        "ElkUrl": "https://x19mclexpr.nie.netease.com/client-log",
        "GameType": 1,
        "Id": project_name,
        "IsMap": is_map,
        "NameSpace": "ec",
        "SaveBackMapPath": project_dir,
        "ShowGuide": False,
        "Source": "import"
    }
    return config

