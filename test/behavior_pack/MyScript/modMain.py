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
