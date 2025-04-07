# -*- coding: utf-8 -*-

# 在这里导入和注册所有的命令模块
from .default_cmd import default_cmd
from .init_cmd import init_cmd
from .add_cmd import add_cmd
from .remove_cmd import remove_cmd
from .modsdk_cmd import modsdk_cmd
from .build_cmd import build_cmd
from .dev_cmd import dev_cmd
from .publish_cmd import publish_cmd
from .mod_cmd import mod_cmd
from .run_cmd import run_cmd

# 导出命令列表，包含所有注册的命令
commands = [
    default_cmd,
    init_cmd,
    add_cmd,
    remove_cmd,
    modsdk_cmd,
    build_cmd,
    dev_cmd,
    publish_cmd,
    mod_cmd,
    run_cmd
]
