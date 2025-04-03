# BP/myScript/config.py
ModName = "MyFirstMod"
ModVersion = "1.0"
ServerSystemName = "MyServerSystem"
ServerSystemCls = "myScript.server.MyServerSystem.MyServerSystem"
ClientSystemName = "MyClientSystem"
ClientSystemCls = "myScript.client.MyClientSystem.MyClientSystem"

# BP/myScript/modMain.py
from mod.common.mod import Mod
import mod.server.extraServerApi as serverApi
import mod.client.extraClientApi as clientApi
from .config import *

@Mod.Binding(name=ModName, version=ModVersion)
class MyFirstMod:

    @Mod.InitServer()
    def serverInit(self): 
        serverApi.RegisterSystem(ModName, ServerSystemName, ServerSystemCls)
        print("{} 服务端已加载！".format(ModName))

    @Mod.InitClient()
    def clientInit(self):
        clientApi.RegisterSystem(ModName, ClientSystemName, ClientSystemCls)
        print("{} 客户端已加载！".format(ModName))

# BP/myScript/server/MyServerSystem.py
import mod.server.extraServerApi as serverApi

from .config import *

ServerSystem = serverApi.GetServerSystemCls()

class MyServerSystem(ServerSystem):

    def __init__(self, namespace, systemName):
        super(MyServerSystem, self).__init__(namespace, systemName)
        print("{} Hello World!".format(ServerSystemName))

# BP/myScript/client/MyClientSystem.py
import mod.client.extraClientApi as clientApi

from .config import *

ClientSystem = clientApi.GetClientSystemCls()

class MyClientSystem(ClientSystem):

    def __init__(self, namespace, systemName):
        super(MyClientSystem, self).__init__(namespace, systemName)
        print("{} Hello World!".format(ClientSystemName))