# -*- coding: utf-8 -*-

import os

def generate_mod_framework(behavior_pack_path, mod_name, mod_version, server_system_name, 
                         server_system_cls, client_system_name, client_system_cls,
                         root_dir_name="myScript"):
    """生成Minecraft Mod框架的文件结构
    
    Args:
        behavior_pack_path: 行为包目录的路径
        mod_name: 模组名称
        mod_version: 模组版本
        server_system_name: 服务器系统名称
        server_system_cls: 服务器系统类路径
        client_system_name: 客户端系统名称
        client_system_cls: 客户端系统类路径
        root_dir_name: 顶级目录名称，默认为"myScript"
        
    Returns:
        bool: 是否成功创建模组框架
        str: 成功消息或错误信息
    """
    try:
        # 创建目录结构，使用用户提供的顶级目录名
        script_dir = os.path.join(behavior_pack_path, root_dir_name)
        server_dir = os.path.join(script_dir, "server")
        client_dir = os.path.join(script_dir, "client")
        
        os.makedirs(script_dir, exist_ok=True)
        os.makedirs(server_dir, exist_ok=True)
        os.makedirs(client_dir, exist_ok=True)
        
        # 创建config.py
        with open(os.path.join(script_dir, "config.py"), "w", encoding="utf-8") as f:
            f.write(f'''# -*- coding: utf-8 -*-

ModName = "{mod_name}"
ModVersion = "{mod_version}"
ServerSystemName = "{server_system_name}"
ServerSystemCls = "{server_system_cls}"
ClientSystemName = "{client_system_name}"
ClientSystemCls = "{client_system_cls}"
''')
        
        # 创建modMain.py
        with open(os.path.join(script_dir, "modMain.py"), "w", encoding="utf-8") as f:
            f.write(f'''# -*- coding: utf-8 -*-

from mod.common.mod import Mod
import mod.server.extraServerApi as serverApi
import mod.client.extraClientApi as clientApi
from .config import *


@Mod.Binding(name=ModName, version=ModVersion)
class {mod_name}:

    @Mod.InitServer()
    def serverInit(self): 
        serverApi.RegisterSystem(ModName, ServerSystemName, ServerSystemCls)
        print("{{}} 服务端已加载！".format(ModName))

    @Mod.InitClient()
    def clientInit(self):
        clientApi.RegisterSystem(ModName, ClientSystemName, ClientSystemCls)
        print("{{}} 客户端已加载！".format(ModName))
''')
        
        # 创建服务端系统文件
        server_system_filename = f"{server_system_name}.py"
        with open(os.path.join(server_dir, server_system_filename), "w", encoding="utf-8") as f:
            f.write(f'''# -*- coding: utf-8 -*-

import mod.server.extraServerApi as serverApi
from ..config import *

ServerSystem = serverApi.GetServerSystemCls()


class {server_system_name}(ServerSystem):

    def __init__(self, namespace, systemName):
        super({server_system_name}, self).__init__(namespace, systemName)
        print("{{}} Hello World!".format(ServerSystemName))
''')
        
        # 创建客户端系统文件
        client_system_filename = f"{client_system_name}.py"
        with open(os.path.join(client_dir, client_system_filename), "w", encoding="utf-8") as f:
            f.write(f'''# -*- coding: utf-8 -*-

import mod.client.extraClientApi as clientApi
from ..config import *

ClientSystem = clientApi.GetClientSystemCls()

class {client_system_name}(ClientSystem):

    def __init__(self, namespace, systemName):
        super({client_system_name}, self).__init__(namespace, systemName)
        print("{{}} Hello World!".format(ClientSystemName))
''')
        
        # 创建__init__.py文件
        with open(os.path.join(script_dir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("# -*- coding: utf-8 -*-")
        with open(os.path.join(server_dir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("# -*- coding: utf-8 -*-")
        with open(os.path.join(client_dir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("# -*- coding: utf-8 -*-")
        
        return True, f"Mod框架已成功创建于 {behavior_pack_path}/{root_dir_name}"
        
    except Exception as e:
        return False, f"创建Mod框架时出错: {str(e)}"
