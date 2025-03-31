# 在这里导入和注册所有的命令模块
from .init_cmd import init_cmd
from .install_cmd import install_cmd
from .modsdk_cmd import modsdk_cmd
from .build_cmd import build_cmd
from .dev_cmd import dev_cmd
from .publish_cmd import publish_cmd
from .default_cmd import default_cmd

# 导出命令列表，包含所有注册的命令
commands = [
    default_cmd,
    init_cmd,
    install_cmd,
    modsdk_cmd,
    build_cmd,
    dev_cmd,
    publish_cmd
]
