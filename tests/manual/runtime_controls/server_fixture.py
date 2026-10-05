# coding: utf-8
"""OPTIONAL GAME-SERVER FIXTURE. Execute only in a disposable local test world.

Not an Addon, not a host-side unit test. This script changes terrain, player
position/mode/hunger/inventory and registers a temporary damage listener.
"""
import math
import sys
import types
import mod.server.extraServerApi as _manual_server_api


class Fixture(_manual_server_api.GetServerSystemCls()):
    def __init__(self, namespace, name):
        _manual_server_api.GetServerSystemCls().__init__(self, namespace, name)
        self.api = _manual_server_api
        self.factory = self.api.GetEngineCompFactory()
        self.level = self.api.GetLevelId()
        self.namespace, self.name = namespace, name
        self.events, self.entities = [], []
        self.cow = None
        self.origin = None
        self.player = None
        self.event = (self.api.GetEngineNamespace(), self.api.GetEngineSystemName(), 'ActuallyHurtServerEvent')
        self.ListenForEvent(*(self.event + (self, self.on_hurt)))

    def on_hurt(self, arguments):
        self.events.append(dict(arguments))
        self.events = self.events[-50:]

    def prepare(self):
        players = self.api.GetPlayerList()
        if len(players) != 1:
            raise ValueError('Fixture requires exactly one player in a disposable local world')
        self.player = players[0]
        position = self.factory.CreatePos(self.player).GetFootPos()
        self.origin = (int(math.floor(position[0])), min(240, max(64, int(position[1]) + 3)),
                       int(math.floor(position[2])))
        x, y, z = self.origin
        player = self.factory.CreatePlayer(self.player)
        player.SetPlayerGameType(1)
        block = self.factory.CreateBlockInfo(self.level)
        def set_block(position, name):
            existing = block.GetBlockNew(position, 0)
            if existing and existing.get('name') == name:
                return
            accepted = block.SetBlockNew(position, {'name': name, 'aux': 0}, 0, 0)
            observed = block.GetBlockNew(position, 0)
            # An unchanged block can return False; readback is the useful check.
            if accepted is False and (not observed or observed.get('name') != name):
                raise ValueError('Test arena chunk not writable: '+str(position))
        for dx in range(-5, 6):
            for dz in range(-5, 9):
                set_block((x+dx, y, z+dz), 'minecraft:stone')
                for dy in range(1, 6):
                    set_block((x+dx, y+dy, z+dz), 'minecraft:air')
        self.reset_player()
        for slot, name, count in ((0, 'cobblestone', 64), (1, 'wooden_sword', 1),
                                  (2, 'apple', 3), (3, 'bow', 1), (4, 'arrow', 16),
                                  (5, 'diamond_pickaxe', 1)):
            self.factory.CreateItem(self.player).SpawnItemToPlayerInv(
                {'newItemName': 'minecraft:'+name, 'newAuxValue': 0, 'count': count}, self.player, slot)
        return {'ok': True, 'origin': list(self.origin), 'position': list(self.position()),
                'player': self.player, 'hunger': player.GetPlayerHunger()}

    def position(self):
        return (self.origin[0]+.5, self.origin[1]+1., self.origin[2]+.5)

    def reset_player(self):
        self.factory.CreatePos(self.player).SetFootPos(self.position())
        self.factory.CreatePlayer(self.player).SetPlayerGameType(0)
        self.factory.CreatePlayer(self.player).SetPlayerHunger(10)
        return {'ok': True, 'position': list(self.position())}

    def readback(self):
        item = self.factory.CreateItem(self.player)
        inventory = self.api.GetMinecraftEnum().ItemPosType.INVENTORY
        return {'ok': True, 'hunger': self.factory.CreatePlayer(self.player).GetPlayerHunger(),
                'food': item.GetPlayerItem(inventory, 2), 'arrows': item.GetPlayerItem(inventory, 4),
                'position': list(self.factory.CreatePos(self.player).GetFootPos()),
                'events': list(self.events)}

    def health(self):
        return self.factory.CreateAttr(self.cow).GetAttrValue(self.api.GetMinecraftEnum().AttrType.HEALTH)

    def target_geometry(self):
        position = self.factory.CreatePos(self.cow).GetFootPos()
        size = self.factory.CreateCollisionBox(self.cow).GetSize()
        if not position or not size or len(size) != 2 or size[1] <= 0:
            raise ValueError('Target collision box is not available')
        return {'ok': True, 'entity': self.cow, 'health': self.health(), 'collision_size': list(size),
                'aim': [position[0], position[1]+size[1]*.5, position[2]]}

    def spawn_target(self, age=None):
        if self.cow:
            self.DestroyEntity(self.cow)
            if self.cow in self.entities: self.entities.remove(self.cow)
        self.reset_player()
        x, y, z = self.origin
        self.cow = self.CreateEngineEntityByTypeStr('minecraft:cow', (x+.5, y+1., z+3.5), (0, 0), 0)
        if not self.cow:
            raise ValueError('Engine did not create the test target')
        self.entities.append(self.cow)
        if age is not None:
            event = {'adult': 'minecraft:ageable_grow_up', 'baby': 'minecraft:entity_born'}[age]
            if not self.factory.CreateEntityEvent(self.cow).TriggerCustomEvent(self.cow, event):
                raise ValueError('Could not select fixture age: '+age)
        self.factory.CreateControlAi(self.cow).SetBlockControlAi(False, True)
        health = self.factory.CreateAttr(self.cow)
        kind = self.api.GetMinecraftEnum().AttrType.HEALTH
        health.SetAttrMaxValue(kind, 100.)
        health.SetAttrValue(kind, 100.)
        return self.target_geometry()

    def aim_for_bow(self):
        x, y, z = self.origin
        self.factory.CreatePos(self.cow).SetFootPos((x+.5, y+1., z+4.5))
        self.events = []
        return self.target_geometry()

    def prepare_block(self):
        for entity in self.entities:
            self.DestroyEntity(entity)
        self.entities = []
        self.reset_player()
        self.factory.CreatePlayer(self.player).SetPlayerGameType(1)
        x, y, z = self.origin
        self.original_block, self.placed_block = (x, y+2, z+3), (x, y+2, z+2)
        block = self.factory.CreateBlockInfo(self.level)
        block.SetBlockNew(self.placed_block, {'name': 'minecraft:air', 'aux': 0}, 0, 0)
        block.SetBlockNew(self.original_block, {'name': 'minecraft:stone', 'aux': 0}, 0, 0)
        return {'ok': True, 'aim': [x+.5, y+2.5, z+3.5], 'placed_position': list(self.placed_block)}

    def block_readback(self):
        return self.factory.CreateBlockInfo(self.level).GetBlockNew(self.placed_block, 0)

    def survival(self):
        self.factory.CreatePlayer(self.player).SetPlayerGameType(0)
        return {'ok': True}

    def cleanup(self):
        for entity in self.entities:
            self.DestroyEntity(entity)
        self.entities = []
        self.UnListenForEvent(*(self.event + (self, self.on_hurt)))
        unregister = getattr(self.api, 'DestroySystem', None) or getattr(self.api, 'UnRegisterSystem', None)
        if callable(unregister):
            unregister(self.namespace, self.name)
        return {'ok': True, 'terrain_and_inventory_restored': False}


_manual_module_name = '_mcpy_optional_controls_fixture'
if _manual_module_name in sys.modules:
    raise ValueError('A manual fixture already exists; clean it up before preparing another')
_manual_module = types.ModuleType(_manual_module_name)
_manual_module.Fixture = Fixture
sys.modules[_manual_module_name] = _manual_module
manual_fixture = _manual_server_api.RegisterSystem('mcpy_optional_controls', 'fixture',
                                                   _manual_module_name+'.Fixture')
_manual_module.fixture = manual_fixture
_result = manual_fixture.prepare()
