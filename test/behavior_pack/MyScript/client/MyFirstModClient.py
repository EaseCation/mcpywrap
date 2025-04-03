import mod.client.extraClientApi as clientApi
from ..config import *

ClientSystem = clientApi.GetClientSystemCls()

class MyFirstModClientSystem(ClientSystem):

    def __init__(self, namespace, systemName):
        super(MyFirstModClientSystem, self).__init__(namespace, systemName)
        print("{} Hello World!".format(ClientSystemName))
