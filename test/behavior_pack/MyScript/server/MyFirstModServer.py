import mod.server.extraServerApi as serverApi
from ..config import *

ServerSystem = serverApi.GetServerSystemCls()

class MyFirstModServerSystem(ServerSystem):

    def __init__(self, namespace, systemName):
        super(MyFirstModServerSystem, self).__init__(namespace, systemName)
        print("{} Hello World!".format(ServerSystemName))
