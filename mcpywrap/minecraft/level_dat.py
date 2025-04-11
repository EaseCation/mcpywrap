import os
import sys
import io
import datetime
import uuid
import struct
import random
from collections import OrderedDict

# 自定义 NBT 标签类型
class TagType:
    """NBT 标签类型枚举"""
    END = 0
    BYTE = 1
    SHORT = 2
    INT = 3
    LONG = 4
    FLOAT = 5
    DOUBLE = 6
    BYTE_ARRAY = 7
    STRING = 8
    LIST = 9
    COMPOUND = 10
    INT_ARRAY = 11
    LONG_ARRAY = 12

# 自定义 NBT 标签基类
class NBTTag:
    """NBT 标签基类"""
    def __init__(self, value=None):
        self.value = value
    
    def __str__(self):
        return str(self.value)
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.value!r})"

class TAG_End(NBTTag):
    tag_type = TagType.END
    
    def __init__(self):
        super().__init__(None)
    
    def write_tag(self, buffer):
        pass
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        return cls()

class TAG_Byte(NBTTag):
    tag_type = TagType.BYTE
    
    def __init__(self, value):
        super().__init__(value)
    
    def write_tag(self, buffer, little_endian=True):
        buffer.write(struct.pack("b", self.value))
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        return cls(struct.unpack("b", buffer.read(1))[0])

class TAG_Short(NBTTag):
    tag_type = TagType.SHORT
    
    def __init__(self, value):
        super().__init__(value)
    
    def write_tag(self, buffer, little_endian=True):
        fmt = "<h" if little_endian else ">h"
        buffer.write(struct.pack(fmt, self.value))
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        fmt = "<h" if little_endian else ">h"
        return cls(struct.unpack(fmt, buffer.read(2))[0])

class TAG_Int(NBTTag):
    tag_type = TagType.INT
    
    def __init__(self, value):
        super().__init__(value)
    
    def write_tag(self, buffer, little_endian=True):
        fmt = "<i" if little_endian else ">i"
        buffer.write(struct.pack(fmt, self.value))
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        fmt = "<i" if little_endian else ">i"
        return cls(struct.unpack(fmt, buffer.read(4))[0])

class TAG_Long(NBTTag):
    tag_type = TagType.LONG
    
    def __init__(self, value):
        super().__init__(value)
    
    def write_tag(self, buffer, little_endian=True):
        fmt = "<q" if little_endian else ">q"
        buffer.write(struct.pack(fmt, self.value))
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        fmt = "<q" if little_endian else ">q"
        return cls(struct.unpack(fmt, buffer.read(8))[0])

class TAG_Float(NBTTag):
    tag_type = TagType.FLOAT
    
    def __init__(self, value):
        super().__init__(value)
    
    def write_tag(self, buffer, little_endian=True):
        fmt = "<f" if little_endian else ">f"
        buffer.write(struct.pack(fmt, self.value))
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        fmt = "<f" if little_endian else ">f"
        return cls(struct.unpack(fmt, buffer.read(4))[0])

class TAG_Double(NBTTag):
    tag_type = TagType.DOUBLE
    
    def __init__(self, value):
        super().__init__(value)
    
    def write_tag(self, buffer, little_endian=True):
        fmt = "<d" if little_endian else ">d"
        buffer.write(struct.pack(fmt, self.value))
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        fmt = "<d" if little_endian else ">d"
        return cls(struct.unpack(fmt, buffer.read(8))[0])

class TAG_String(NBTTag):
    tag_type = TagType.STRING
    
    def __init__(self, value):
        super().__init__(value)
    
    def write_tag(self, buffer, little_endian=True):
        data = self.value.encode("utf-8")
        fmt = "<H" if little_endian else ">H"
        buffer.write(struct.pack(fmt, len(data)))
        buffer.write(data)
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        fmt = "<H" if little_endian else ">H"
        length = struct.unpack(fmt, buffer.read(2))[0]
        data = buffer.read(length)
        return cls(data.decode("utf-8"))

class TAG_List(NBTTag):
    tag_type = TagType.LIST
    
    def __init__(self, tag_type=0, values=None):
        self.list_type = tag_type
        super().__init__(values or [])
    
    def __getitem__(self, key):
        return self.value[key]
    
    def __setitem__(self, key, value):
        self.value[key] = value
    
    def __iter__(self):
        return iter(self.value)
    
    def __len__(self):
        return len(self.value)
    
    def append(self, value):
        self.value.append(value)
    
    def write_tag(self, buffer, little_endian=True):
        buffer.write(struct.pack("b", self.list_type))
        fmt = "<i" if little_endian else ">i"
        buffer.write(struct.pack(fmt, len(self.value)))
        
        for item in self.value:
            item.write_tag(buffer, little_endian)
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        tag_type = struct.unpack("b", buffer.read(1))[0]
        fmt = "<i" if little_endian else ">i"
        length = struct.unpack(fmt, buffer.read(4))[0]
        
        tag_class = TAG_CLASSES.get(tag_type)
        if not tag_class:
            raise ValueError(f"Unknown tag type: {tag_type}")
        
        result = cls(tag_type, [])
        for _ in range(length):
            result.value.append(tag_class.read_tag(buffer, little_endian))
        
        return result

class TAG_Compound(NBTTag):
    tag_type = TagType.COMPOUND
    
    def __init__(self, value=None):
        super().__init__(value or OrderedDict())
    
    def __getitem__(self, key):
        return self.value[key]
    
    def __setitem__(self, key, value):
        self.value[key] = value
    
    def __contains__(self, key):
        return key in self.value
    
    def get(self, key, default=None):
        return self.value.get(key, default)
    
    def write_tag(self, buffer, little_endian=True):
        for name, tag in self.value.items():
            buffer.write(struct.pack("b", tag.tag_type))
            
            # 写入名称
            name_bytes = name.encode("utf-8")
            fmt = "<H" if little_endian else ">H"
            buffer.write(struct.pack(fmt, len(name_bytes)))
            buffer.write(name_bytes)
            
            # 写入值
            tag.write_tag(buffer, little_endian)
        
        # 写入结束标记
        buffer.write(struct.pack("b", 0))
    
    @classmethod
    def read_tag(cls, buffer, little_endian=True):
        result = cls()
        
        while True:
            tag_type = struct.unpack("b", buffer.read(1))[0]
            if tag_type == 0:  # END 标签
                break
            
            # 读取名称
            fmt = "<H" if little_endian else ">H"
            name_length = struct.unpack(fmt, buffer.read(2))[0]
            name = buffer.read(name_length).decode("utf-8")
            
            # 读取标签值
            tag_class = TAG_CLASSES.get(tag_type)
            if not tag_class:
                raise ValueError(f"Unknown tag type: {tag_type}")
            
            result.value[name] = tag_class.read_tag(buffer, little_endian)
        
        return result

# 注册标签类
TAG_CLASSES = {
    TagType.END: TAG_End,
    TagType.BYTE: TAG_Byte,
    TagType.SHORT: TAG_Short,
    TagType.INT: TAG_Int,
    TagType.LONG: TAG_Long,
    TagType.FLOAT: TAG_Float,
    TagType.DOUBLE: TAG_Double,
    TagType.STRING: TAG_String,
    TagType.LIST: TAG_List,
    TagType.COMPOUND: TAG_Compound
}

class NamedTag:
    """命名的 NBT 标签"""
    def __init__(self, tag, name=""):
        self.tag = tag
        self.name = name
        self.compound = tag  # 兼容属性
    
    def save_to(self, buffer, little_endian=True):
        """保存到缓冲区"""
        buffer.write(struct.pack("b", self.tag.tag_type))
        
        # 写入名称
        name_bytes = self.name.encode("utf-8")
        fmt = "<H" if little_endian else ">H"
        buffer.write(struct.pack(fmt, len(name_bytes)))
        buffer.write(name_bytes)
        
        # 写入标签值
        self.tag.write_tag(buffer, little_endian)

def load(buffer, little_endian=True):
    """从字节缓冲区加载 NBT 数据"""
    tag_type = struct.unpack("b", buffer.read(1))[0]
    
    # 读取根标签名称
    fmt = "<H" if little_endian else ">H"
    name_length = struct.unpack(fmt, buffer.read(2))[0]
    name = buffer.read(name_length).decode("utf-8")
    
    # 读取根标签值
    tag_class = TAG_CLASSES.get(tag_type)
    if not tag_class:
        raise ValueError(f"Unknown root tag type: {tag_type}")
    
    tag = tag_class.read_tag(buffer, little_endian)
    return NamedTag(tag, name)

# 别名，兼容原有代码
String = TAG_String
Int = TAG_Int
Byte = TAG_Byte
Float = TAG_Float
Long = TAG_Long
List = TAG_List
Compound = TAG_Compound

class BedrockNBT:
    """Minecraft 基岩版 NBT 文件操作类"""
    
    def __init__(self, nbt_data=None, header=None):
        """
        初始化 BedrockNBT 对象
        
        Args:
            nbt_data (NamedTag, optional): NBT 数据对象
            header (bytes, optional): 文件头部数据（基岩版特有，通常为 8 字节）
        """
        self.nbt_data = nbt_data
        self.header = header or b'\x0A\x00\x00\x00\x41\x0B\x00\x00'  # 默认头部
        self.compound = getattr(nbt_data, 'compound', nbt_data) if nbt_data else None
        
    @classmethod
    def load_file(cls, path, skip_bytes=8, try_all=True):
        """
        从文件加载 NBT 数据
        
        Args:
            path (str): NBT 文件路径
            skip_bytes (int, optional): 跳过的字节数，基岩版通常为 8
            try_all (bool, optional): 是否尝试不同的跳过字节数
            
        Returns:
            BedrockNBT: 加载的 NBT 数据对象
        """
        # 读取文件
        with open(path, 'rb') as f:
            data = f.read()
            
        print(f"文件大小: {len(data)} 字节")
        print(f"文件头部: {' '.join([f'{b:02X}' for b in data[:16]])}")
        
        # 保存头部
        header = data[:skip_bytes]
        
        # 尝试加载数据
        nbt_data = cls._load_nbt_data(data, skip_bytes)
        
        # 如果加载失败并且 try_all 为 True，则尝试不同的跳过字节数
        if (nbt_data is None or 
            (hasattr(nbt_data, 'compound') and not nbt_data.compound)) and try_all:
            print("NBT 数据为空，尝试不同的跳过字节数...")
            
            for skip in [0, 4, 12, 16]:
                if skip == skip_bytes:
                    continue
                    
                print(f"尝试跳过 {skip} 字节...")
                nbt_data = cls._load_nbt_data(data, skip)
                
                if nbt_data and hasattr(nbt_data, 'compound') and nbt_data.compound:
                    print(f"成功读取！跳过 {skip} 字节")
                    header = data[:skip]  # 更新头部为实际的字节数
                    break
        
        if nbt_data is None or (hasattr(nbt_data, 'compound') and not nbt_data.compound):
            print("无法读取有效的 NBT 数据")
            return None
            
        return cls(nbt_data, header)
    
    @staticmethod
    def _load_nbt_data(data, skip_bytes):
        """
        加载 NBT 数据
        
        Args:
            data (bytes): 完整的文件数据
            skip_bytes (int): 要跳过的字节数
            
        Returns:
            NamedTag: 加载的 NBT 数据
        """
        try:
            # 跳过指定字节数
            actual_data = data[skip_bytes:]
            
            # 使用 BytesIO 包装处理后的数据
            data_stream = io.BytesIO(actual_data)
            
            # 加载数据
            return load(data_stream, little_endian=True)
        except Exception as e:
            print(f"加载 NBT 数据失败 (跳过 {skip_bytes} 字节): {e}")
            return None
    
    def save_file(self, path, create_backup=True):
        """
        保存 NBT 数据到文件
        
        Args:
            path (str): 保存的文件路径
            create_backup (bool, optional): 是否创建备份
            
        Returns:
            bool: 是否成功保存
        """
        if self.nbt_data is None:
            print("没有 NBT 数据可保存")
            return False
            
        try:
            # 创建备份
            if create_backup and os.path.exists(path):
                backup_path = path + f".backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
                with open(path, "rb") as src, open(backup_path, "wb") as dst:
                    dst.write(src.read())
                print(f"已创建备份: {backup_path}")
            
            # 将 NBT 数据保存到临时缓冲区
            buffer = io.BytesIO()
            self.nbt_data.save_to(buffer, little_endian=True)
            buffer.seek(0)
            nbt_bytes = buffer.read()
            
            # 保存文件
            with open(path, "wb") as f:
                f.write(self.header)  # 写入头部
                f.write(nbt_bytes)    # 写入 NBT 数据
                
            print(f"已成功保存到: {path}")
            return True
            
        except Exception as e:
            print(f"保存文件失败: {e}")
            return False
    
    @classmethod
    def create_new(cls, level_name="New World", game_type=0, generator=1):
        """
        创建新的 level.dat 文件数据
        
        Args:
            level_name (str): 世界名称
            game_type (int): 游戏模式 (0=生存, 1=创造, 2=冒险, 3=旁观者)
            generator (int): 地形生成器类型 (1=无限, 2=平坦)
            
        Returns:
            BedrockNBT: 新创建的 NBT 数据对象
        """
        # 创建根复合标签
        root = Compound()
        
        # 基本世界设置
        root["BiomeOverride"] = String("")
        root["CenterMapsToOrigin"] = Byte(0)
        root["ConfirmedPlatformLockedContent"] = Byte(0)
        root["Difficulty"] = Int(2)  # 普通难度
        
        # 平坦世界层设置
        flat_layers = {
            "biome_id": 1,
            "block_layers": [
                {"block_name": "minecraft:bedrock", "count": 1},
                {"block_name": "minecraft:dirt", "count": 2},
                {"block_name": "minecraft:grass", "count": 1}
            ],
            "encoding_version": 6,
            "structure_options": None,
            "world_version": "version.post_1_18"
        }
        root["FlatWorldLayers"] = String(str(flat_layers).replace("'", "\""))
        
        root["ForceGameType"] = Byte(0)
        root["GameType"] = Int(game_type)
        root["Generator"] = Int(generator)
        root["InventoryVersion"] = String("1.20.50")
        root["LANBroadcast"] = Byte(1)
        root["LANBroadcastIntent"] = Byte(1)
        root["LastPlayed"] = Long(int(datetime.datetime.now().timestamp()))
        root["LevelName"] = String(level_name)
        root["LimitedWorldOriginX"] = Int(0)
        root["LimitedWorldOriginY"] = Int(32767)
        root["LimitedWorldOriginZ"] = Int(0)
        
        # 最低兼容客户端版本
        min_client_version = List(TagType.INT, [Int(1), Int(20), Int(51), Int(0), Int(0)])
        root["MinimumCompatibleClientVersion"] = min_client_version
        
        root["MultiplayerGame"] = Byte(1)
        root["MultiplayerGameIntent"] = Byte(1)
        root["NetherScale"] = Int(8)
        root["NetworkVersion"] = Int(630)
        root["Platform"] = Int(2)
        root["PlatformBroadcastIntent"] = Int(3)
        
        # 随机种子
        root["RandomSeed"] = Long(random.randint(-9223372036854775808, 9223372036854775807))
        
        root["SpawnV1Villagers"] = Byte(0)
        root["SpawnX"] = Int(0)
        root["SpawnY"] = Int(64)
        root["SpawnZ"] = Int(0)
        root["StorageVersion"] = Int(10)
        root["Time"] = Long(0)
        root["WorldVersion"] = Int(1)
        root["XBLBroadcastIntent"] = Int(3)
        
        # 玩家能力
        abilities = Compound()
        abilities["attackmobs"] = Byte(1)
        abilities["attackplayers"] = Byte(1)
        abilities["build"] = Byte(1)
        abilities["doorsandswitches"] = Byte(1)
        abilities["flySpeed"] = Float(0.05)
        abilities["flying"] = Byte(0)
        abilities["instabuild"] = Byte(0)
        abilities["invulnerable"] = Byte(0)
        abilities["lightning"] = Byte(0)
        abilities["mayfly"] = Byte(0)
        abilities["mine"] = Byte(1)
        abilities["op"] = Byte(0)
        abilities["opencontainers"] = Byte(1)
        abilities["teleport"] = Byte(0)
        abilities["walkSpeed"] = Float(0.1)
        root["abilities"] = abilities
        
        # 其他常见设置
        root["bonusChestEnabled"] = Byte(0)
        root["bonusChestSpawned"] = Byte(0)
        root["cheatsEnabled"] = Byte(0)
        root["commandblockoutput"] = Byte(1)
        root["commandblocksenabled"] = Byte(1)
        root["commandsEnabled"] = Byte(1)
        root["currentTick"] = Long(0)
        root["daylightCycle"] = Int(0)
        root["dodaylightcycle"] = Byte(1)
        root["doentitydrops"] = Byte(1)
        root["dofiretick"] = Byte(1)
        root["doimmediaterespawn"] = Byte(0)
        root["doinsomnia"] = Byte(1)
        root["dolimitedcrafting"] = Byte(0)
        root["domobloot"] = Byte(1)
        root["domobspawning"] = Byte(1)
        root["dotiledrops"] = Byte(1)
        root["doweathercycle"] = Byte(1)
        root["drowningdamage"] = Byte(1)
        root["falldamage"] = Byte(1)
        root["firedamage"] = Byte(1)
        root["freezedamage"] = Byte(1)
        root["functioncommandlimit"] = Int(10000)
        root["hasBeenLoadedInCreative"] = Byte(0)
        root["hasLockedBehaviorPack"] = Byte(0)
        root["hasLockedResourcePack"] = Byte(0)
        root["immutableWorld"] = Byte(0)
        root["keepinventory"] = Byte(0)
        
        # 版本信息
        last_version = List(TagType.INT, [Int(1), Int(20), Int(51), Int(0), Int(0)])
        root["lastOpenedWithVersion"] = last_version
        
        root["lightningLevel"] = Float(0.0)
        root["lightningTime"] = Int(0)
        root["limitedWorldDepth"] = Int(16)
        root["limitedWorldWidth"] = Int(16)
        root["maxcommandchainlength"] = Int(65536)
        root["mobgriefing"] = Byte(1)
        root["naturalregeneration"] = Byte(1)
        root["permissionsLevel"] = Int(1)
        root["playerPermissionsLevel"] = Int(1)
        root["playerssleepingpercentage"] = Int(100)
        root["pvp"] = Byte(1)
        root["rainLevel"] = Float(0.0)
        root["rainTime"] = Int(0)
        root["randomtickspeed"] = Int(1)
        root["recipesunlock"] = Byte(1)
        root["requiresCopiedPackRemovalCheck"] = Byte(0)
        root["respawnblocksexplode"] = Byte(1)
        root["sendcommandfeedback"] = Byte(1)
        root["serverChunkTickRange"] = Int(4)
        root["showbordereffect"] = Byte(1)
        root["showcoordinates"] = Byte(0)
        root["showdeathmessages"] = Byte(1)
        root["showrecipemessages"] = Byte(1)
        root["showtags"] = Byte(1)
        root["spawnMobs"] = Byte(1)
        root["spawnradius"] = Int(5)
        root["startWithMapEnabled"] = Byte(0)
        root["texturePacksRequired"] = Byte(0)
        root["tntexplodes"] = Byte(1)
        root["useMsaGamertagsOnly"] = Byte(0)
        root["worldStartCount"] = Int(0)
        
        # 空世界策略
        root["world_policies"] = Compound()
        
        # 创建 NamedTag 对象
        nbt_data = NamedTag(root, "")
        
        # 默认头部
        header = b'\x0A\x00\x00\x00\x41\x0B\x00\x00'
        
        return cls(nbt_data, header)
    
    def get_value(self, key, default=None):
        """
        获取 NBT 数据中的值
        
        Args:
            key (str): 键名
            default: 默认值
            
        Returns:
            任意类型: 对应键的值
        """
        if not self.compound or key not in self.compound:
            return default
            
        value = self.compound[key]
        if hasattr(value, 'value'):
            return value.value
        return value
    
    def set_value(self, key, value):
        """
        设置 NBT 数据中的值
        
        Args:
            key (str): 键名
            value: 要设置的值
            
        Returns:
            bool: 是否成功设置
        """
        if not self.compound:
            print("NBT 数据为空，无法设置值")
            return False
            
        try:
            # 根据值类型自动选择标签类型
            if isinstance(value, str):
                self.compound[key] = String(value)
            elif isinstance(value, int):
                if -128 <= value <= 127:
                    self.compound[key] = Byte(value)
                else:
                    self.compound[key] = Int(value)
            elif isinstance(value, float):
                self.compound[key] = Float(value)
            elif isinstance(value, bool):
                self.compound[key] = Byte(1 if value else 0)
            else:
                print(f"不支持的值类型: {type(value)}")
                return False
                
            return True
        except Exception as e:
            print(f"设置值失败: {e}")
            return False
    
    def get_level_name(self):
        """获取世界名称"""
        return self.get_value("LevelName", "Unknown")
    
    def set_level_name(self, name):
        """设置世界名称"""
        return self.set_value("LevelName", name)
    
    def get_game_type(self):
        """获取游戏模式"""
        return self.get_value("GameType", 0)
    
    def set_game_type(self, game_type):
        """设置游戏模式"""
        if game_type not in [0, 1, 2, 3]:
            print(f"无效的游戏模式: {game_type}")
            return False
        return self.set_value("GameType", game_type)
    
    def get_spawn_position(self):
        """获取出生点位置"""
        x = self.get_value("SpawnX", 0)
        y = self.get_value("SpawnY", 64)
        z = self.get_value("SpawnZ", 0)
        return (x, y, z)
    
    def set_spawn_position(self, x, y, z):
        """设置出生点位置"""
        success = True
        success &= self.set_value("SpawnX", x)
        success &= self.set_value("SpawnY", y)
        success &= self.set_value("SpawnZ", z)
        return success
    
    def toggle_cheat(self, enabled=True):
        """启用或禁用作弊"""
        return self.set_value("cheatsEnabled", 1 if enabled else 0)
    
    def toggle_keep_inventory(self, enabled=True):
        """启用或禁用死亡不掉落"""
        return self.set_value("keepinventory", 1 if enabled else 0)
    
    def print_info(self):
        """打印主要世界信息"""
        if not self.compound:
            print("NBT 数据为空")
            return
            
        print("=== 世界基本信息 ===")
        
        # 世界名称
        print(f"世界名称: {self.get_level_name()}")
        
        # 游戏模式
        game_type = self.get_game_type()
        game_types = {0: "生存模式", 1: "创造模式", 2: "冒险模式", 3: "旁观者模式"}
        print(f"游戏模式: {game_types.get(game_type, f'未知({game_type})')}")
        
        # 出生点
        x, y, z = self.get_spawn_position()
        print(f"出生点坐标: X={x}, Y={y}, Z={z}")
        
        # 难度
        difficulty = self.get_value("Difficulty", 2)
        difficulties = {0: "和平", 1: "简单", 2: "普通", 3: "困难"}
        print(f"难度: {difficulties.get(difficulty, f'未知({difficulty})')}")
        
        # 作弊状态
        cheats = self.get_value("cheatsEnabled", 0)
        print(f"作弊: {'已启用' if cheats else '已禁用'}")
        
        # 死亡不掉落
        keep_inventory = self.get_value("keepinventory", 0)
        print(f"死亡不掉落: {'已启用' if keep_inventory else '已禁用'}")
        
        # 种子
        seed = self.get_value("RandomSeed", 0)
        print(f"世界种子: {seed}")
        
        # 游戏时间
        time = self.get_value("Time", 0)
        print(f"游戏时间: {time}")
        
        # 最后游玩时间
        last_played = self.get_value("LastPlayed", 0)
        if last_played:
            try:
                datetime_obj = datetime.datetime.fromtimestamp(last_played)
                print(f"最后游玩时间: {datetime_obj.strftime('%Y-%m-%d %H:%M:%S')}")
            except:
                print(f"最后游玩时间: {last_played}")
        
        # 世界版本
        version_list = self.get_value("lastOpenedWithVersion")
        if version_list and hasattr(version_list, '__iter__'):
            version_str = ".".join([str(v.value) if hasattr(v, 'value') else str(v) for v in version_list[:3]])
            print(f"游戏版本: {version_str}")


def create_world_directory(base_path, world_name=None):
    """
    创建一个全新的 Minecraft 基岩版世界目录
    
    Args:
        base_path (str): 基础路径，通常是 minecraftWorlds 目录
        world_name (str, optional): 世界名称，如果为 None 则自动生成
        
    Returns:
        tuple: (世界路径, 世界ID)
    """
    # 确保基础路径存在
    if not os.path.exists(base_path):
        os.makedirs(base_path)
    
    # 生成世界 ID（UUID）
    world_id = str(uuid.uuid4())
    
    # 创建世界目录
    world_path = os.path.join(base_path, world_id)
    os.makedirs(world_path, exist_ok=True)
    
    # 创建 db 目录
    db_path = os.path.join(world_path, "db")
    os.makedirs(db_path, exist_ok=True)
    
    # 创建 level.dat 文件
    level_dat_path = os.path.join(world_path, "level.dat")
    
    # 创建 NBT 数据
    if not world_name:
        world_name = f"New World {datetime.datetime.now().strftime('%Y-%m-%d')}"
    
    nbt = BedrockNBT.create_new(level_name=world_name)
    nbt.save_file(level_dat_path, create_backup=False)
    
    print(f"已创建新世界: {world_name}")
    print(f"世界ID: {world_id}")
    print(f"路径: {world_path}")
    
    return world_path, world_id


if __name__ == "__main__":
    # 解析命令行参数
    import argparse
    
    parser = argparse.ArgumentParser(description="Minecraft 基岩版 NBT 文件操作工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # 读取命令
    read_parser = subparsers.add_parser("read", help="读取 level.dat 文件")
    read_parser.add_argument("path", help="level.dat 文件路径")
    
    # 修改命令
    modify_parser = subparsers.add_parser("modify", help="修改 level.dat 文件")
    modify_parser.add_argument("path", help="level.dat 文件路径")
    modify_parser.add_argument("--name", help="设置世界名称")
    modify_parser.add_argument("--gametype", type=int, choices=[0, 1, 2, 3], help="设置游戏模式 (0=生存, 1=创造, 2=冒险, 3=旁观者)")
    modify_parser.add_argument("--cheat", type=int, choices=[0, 1], help="设置作弊模式 (0=禁用, 1=启用)")
    modify_parser.add_argument("--keepinv", type=int, choices=[0, 1], help="设置死亡不掉落 (0=禁用, 1=启用)")
    modify_parser.add_argument("--spawnx", type=int, help="设置出生点 X 坐标")
    modify_parser.add_argument("--spawny", type=int, help="设置出生点 Y 坐标")
    modify_parser.add_argument("--spawnz", type=int, help="设置出生点 Z 坐标")
    
    # 创建命令
    create_parser = subparsers.add_parser("create", help="创建新的 level.dat 文件")
    create_parser.add_argument("path", help="保存 level.dat 的路径")
    create_parser.add_argument("--name", default="New World", help="世界名称")
    create_parser.add_argument("--gametype", type=int, choices=[0, 1, 2, 3], default=0, help="游戏模式 (0=生存, 1=创造, 2=冒险, 3=旁观者)")
    
    # 创建世界命令
    create_world_parser = subparsers.add_parser("create-world", help="创建完整的 Minecraft 世界目录")
    create_world_parser.add_argument("path", help="世界目录的基础路径 (通常是 minecraftWorlds 目录)")
    create_world_parser.add_argument("--name", help="世界名称")
    
    args = parser.parse_args()
    
    # 如果没有指定命令，进入交互模式
    if not args.command:
        print("Minecraft 基岩版 NBT 文件操作工具")
        print("1. 读取 level.dat 文件")
        print("2. 修改 level.dat 文件")
        print("3. 创建新的 level.dat 文件")
        print("4. 创建完整的 Minecraft 世界目录")
        
        choice = input("请选择操作 (1-4): ")
        
        if choice == "1":
            args.command = "read"
            args.path = input("请输入 level.dat 文件路径: ")
        elif choice == "2":
            args.command = "modify"
            args.path = input("请输入 level.dat 文件路径: ")
            
            name = input("设置世界名称 (留空保持不变): ")
            args.name = name if name else None
            
            gametype = input("设置游戏模式 (0=生存, 1=创造, 2=冒险, 3=旁观者, 留空保持不变): ")
            args.gametype = int(gametype) if gametype and gametype.isdigit() and int(gametype) in [0, 1, 2, 3] else None
            
            cheat = input("设置作弊模式 (0=禁用, 1=启用, 留空保持不变): ")
            args.cheat = int(cheat) if cheat and cheat in ["0", "1"] else None
            
            keepinv = input("设置死亡不掉落 (0=禁用, 1=启用, 留空保持不变): ")
            args.keepinv = int(keepinv) if keepinv and keepinv in ["0", "1"] else None
        elif choice == "3":
            args.command = "create"
            args.path = input("请输入保存 level.dat 的路径: ")
            args.name = input("设置世界名称 (默认为 New World): ") or "New World"
            
            gametype = input("设置游戏模式 (0=生存, 1=创造, 2=冒险, 3=旁观者, 默认为 0): ")
            args.gametype = int(gametype) if gametype and gametype.isdigit() and int(gametype) in [0, 1, 2, 3] else 0
        elif choice == "4":
            args.command = "create-world"
            args.path = input("请输入世界目录的基础路径 (通常是 minecraftWorlds 目录): ")
            args.name = input("设置世界名称 (留空自动生成): ")
        else:
            print("无效的选择")
            sys.exit(1)
    
    # 执行命令
    if args.command == "read":
        if not os.path.exists(args.path):
            print(f"文件不存在: {args.path}")
            sys.exit(1)
            
        nbt = BedrockNBT.load_file(args.path)
        if nbt:
            nbt.print_info()
    
    elif args.command == "modify":
        if not os.path.exists(args.path):
            print(f"文件不存在: {args.path}")
            sys.exit(1)
            
        nbt = BedrockNBT.load_file(args.path)
        if not nbt:
            sys.exit(1)
            
        nbt.print_info()
        print("\n修改以下属性:")
        
        modified = False
        
        if args.name is not None:
            if nbt.set_level_name(args.name):
                print(f"世界名称已修改为: {args.name}")
                modified = True
        
        if args.gametype is not None:
            if nbt.set_game_type(args.gametype):
                game_types = {0: "生存模式", 1: "创造模式", 2: "冒险模式", 3: "旁观者模式"}
                print(f"游戏模式已修改为: {game_types[args.gametype]}")
                modified = True
                
        if args.cheat is not None:
            if nbt.toggle_cheat(args.cheat == 1):
                print(f"作弊模式已{'启用' if args.cheat == 1 else '禁用'}")
                modified = True
                
        if args.keepinv is not None:
            if nbt.toggle_keep_inventory(args.keepinv == 1):
                print(f"死亡不掉落已{'启用' if args.keepinv == 1 else '禁用'}")
                modified = True
                
        if args.spawnx is not None and args.spawny is not None and args.spawnz is not None:
            if nbt.set_spawn_position(args.spawnx, args.spawny, args.spawnz):
                print(f"出生点已修改为: X={args.spawnx}, Y={args.spawny}, Z={args.spawnz}")
                modified = True
                
        if modified:
            if nbt.save_file(args.path):
                print("修改已保存")
        else:
            print("没有进行任何修改")
    
    elif args.command == "create":
        nbt = BedrockNBT.create_new(level_name=args.name, game_type=args.gametype)
        if nbt.save_file(args.path, create_backup=False):
            print(f"已创建新的 level.dat 文件: {args.path}")
            nbt.print_info()
    
    elif args.command == "create-world":
        create_world_directory(args.path, args.name)