# -*- coding: utf-8 -*-

import click
import os
import subprocess

from ..mcstudio.mcs import *
from .SimpleMonitor import SimpleMonitor
from .discovery import discover_engines, require_resources, studio_installation, DiscoveryError


def open_editor(config_path, engine=None):

    # 获取MC Studio安装目录
    if engine is None:
        try:
            engine = discover_engines().require_engine()
        except DiscoveryError as exc:
            click.echo(str(exc))
            return False
    mcs_download_dir = engine.download_dir
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

def create_editor_config(project_name: str, project_dir: str, is_map: bool, addon_paths: list[str],
                         engine=None, engine_install_dir=None):
    try:
        engine = engine or discover_engines(project_dir).require_engine()
        require_resources(engine, 'editor')
        if engine_install_dir is None:
            engine_install_dir, issues = studio_installation('editor')
            if not engine_install_dir:
                raise DiscoveryError('未找到编辑器安装资源: ' + '; '.join(issues))
    except DiscoveryError as exc:
        click.echo(str(exc))
        return None
    download_path = engine.download_dir
    engine_version = engine.version
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

