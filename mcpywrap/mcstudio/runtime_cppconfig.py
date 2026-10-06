# -*- coding: utf-8 -*-

import os


def gen_runtime_config(engin_version: str, name: str, level_id: str, mcs_download_dir: str, pkg_name: str, beh_links: list[str], res_links: list[str]):
    """
    生成运行时配置文件
    :param engin_version: 引擎版本
    :param name: 世界名称
    :param level_id: 世界ID  带横杠的UUID
    :param mcs_download_dir: MCStudio下载目录
    :param pkg_name: 包名称
    :param beh_links: 行为包链接
    :param res_links: 资源包链接
    """

    data = {
        "version": engin_version,
        "MainComponentId": pkg_name,
        "LocalComponentPathsDict": {},
        "LocalComponentPaths": None,
        "world_info": {
            "level_id": level_id,
            "game_type": 1,
            "difficulty": 2,
            "permission_level": 1,
            "cheat": True,
            "cheat_info": {
                "pvp": True,
                "show_coordinates": False,
                "always_day": False,
                "daylight_cycle": True,
                "fire_spreads": True,
                "tnt_explodes": True,
                "keep_inventory": True,
                "mob_spawn": True,
                "natural_regeneration": True,
                "mob_loot": True,
                "mob_griefing": True,
                "tile_drops": True,
                "entities_drop_loot": True,
                "weather_cycle": True,
                "command_blocks_enabled": True,
                "random_tick_speed": 1,
                "experimental_holiday": False,
                "experimental_biomes": False,
                "fancy_bubbles": False
            },
            "resource_packs": res_links,
            "behavior_packs": beh_links,
            "name": name,
            "world_type": 1,
            "start_with_map": False,
            "bonus_items": False,
            "seed": ""
        },
        "room_info": {
            "ip": "",
            "port": 0,
            "muiltClient": False,
            "room_name": "",
            "token": "",
            "room_id": 0,
            "host_id": 0,
            "allow_pe": True,
            "max_player": 0,
            "visibility_mode": 0,
            "is_pe": False,
            "tag_ids": None,
            "item_ids": []
        },
        "skin_info": {
            "skin": os.path.join(mcs_download_dir, "componentcache", "support", "steve", "steve.png"),
            "slim": False
        }
    }
    return data



# cppconfig is the instance's creation recipe. Engine/session paths are derived.
WORLD_FIELDS = ('name', 'game_type', 'difficulty', 'permission_level', 'cheat',
                'cheat_info', 'world_type', 'start_with_map', 'bonus_items', 'seed')


def validate_world_info(info):
    import re
    if not isinstance(info, dict):
        raise ValueError('cppconfig.world_info 必须是对象')
    for key, values in (('game_type', (0, 1, 2)), ('difficulty', (0, 1, 2, 3)),
                        ('permission_level', (0, 1, 2)), ('world_type', (1, 2))):
        if key in info and (type(info[key]) is not int or info[key] not in values):
            raise ValueError('无效的 world_info.%s：允许 %s' % (key, values))
    for key in ('cheat', 'start_with_map', 'bonus_items'):
        if key in info and type(info[key]) is not bool:
            raise ValueError('world_info.%s 必须是布尔值' % key)
    for key in ('name', 'seed'):
        if key in info and (not isinstance(info[key], str) or '\x00' in info[key]):
            raise ValueError('world_info.%s 必须是字符串' % key)
    if 'name' in info and not info['name'].strip():
        raise ValueError('世界名称不能为空')
    if 'level_id' in info and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(info['level_id'])):
        raise ValueError('world_info.level_id 必须是有效的实例目录名')
    rules = info.get('cheat_info', {})
    if not isinstance(rules, dict):
        raise ValueError('world_info.cheat_info 必须是对象')
    known = gen_runtime_config('', '', 'fixture', '', '', [], [])['world_info']['cheat_info']
    for key, value in rules.items():
        if key not in known:
            raise ValueError('不支持的 world_info.cheat_info 字段：' + key)
        if key == 'random_tick_speed':
            if type(value) is not int or not 0 <= value <= 2147483647:
                raise ValueError('random_tick_speed 必须是非负 32 位整数')
        elif type(value) is not bool:
            raise ValueError('world_info.cheat_info.%s 必须是布尔值' % key)
    return info


def read_cppconfig(path):
    import json
    from pathlib import Path
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('cppconfig 必须是 JSON 对象')
    validate_world_info(data.get('world_info'))
    return data


def creation_settings(source):
    """Import settings only; never inherit identity, credentials or pack paths."""
    from copy import deepcopy
    if source is None:
        return {}
    data = read_cppconfig(source) if not isinstance(source, dict) else source
    info = validate_world_info(data.get('world_info'))
    unknown = set(info) - set(WORLD_FIELDS) - {'level_id', 'behavior_packs', 'resource_packs'}
    if unknown:
        raise ValueError('不支持的 world_info 字段：' + ', '.join(sorted(unknown)))
    return deepcopy({key: info[key] for key in WORLD_FIELDS if key in info})


def write_cppconfig(path, config):
    from pathlib import Path
    from .sessions import save
    validate_world_info(config['world_info'])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, config)


def prepare_cppconfig(path, version, name, level_id, download_dir, package, behaviors, resources, settings=None):
    """Preserve instance options; refresh only backend-generated references."""
    from pathlib import Path
    generated = gen_runtime_config(version, name, level_id, download_dir, package, behaviors, resources)
    if Path(path).exists():
        if settings is not None:
            raise ValueError('创建参数不能覆盖已有实例，请使用 --new')
        config = read_cppconfig(path)
        info = config['world_info']
        if info.get('level_id') != level_id:
            raise ValueError('cppconfig 的世界 ID 与实例不一致')
        # Supply fields absent from legacy configs without replacing user values.
        for key, value in generated['world_info'].items():
            info.setdefault(key, value)
        for key, value in generated.items():
            config.setdefault(key, value)
    else:
        config = generated
        info = config['world_info']
        if settings is not None:
            supplied = creation_settings(settings)
            info['cheat_info'].update(supplied.pop('cheat_info', {}))
            info.update(supplied)
    config.update(version=version, MainComponentId=package,
                  LocalComponentPathsDict={}, LocalComponentPaths=None)
    config['skin_info'] = generated['skin_info']
    info.update(behavior_packs=behaviors, resource_packs=resources)
    write_cppconfig(path, config)
    return config


# Read-only mapping from the native Bedrock save. Never edit a live level.dat.
NBT_WORLD_FIELDS = {'GameType': 'game_type', 'Difficulty': 'difficulty', 'LevelName': 'name',
                    'Generator': 'world_type', 'RandomSeed': 'seed', 'commandsEnabled': 'cheat',
                    'bonusChestEnabled': 'bonus_items', 'startWithMapEnabled': 'start_with_map',
                    'playerPermissionsLevel': 'permission_level'}
NBT_RULES = {'pvp': 'pvp', 'showcoordinates': 'show_coordinates', 'dodaylightcycle': 'daylight_cycle',
             'dofiretick': 'fire_spreads', 'tntexplodes': 'tnt_explodes', 'keepinventory': 'keep_inventory',
             'domobspawning': 'mob_spawn', 'naturalregeneration': 'natural_regeneration',
             'domobloot': 'mob_loot', 'mobgriefing': 'mob_griefing', 'dotiledrops': 'tile_drops',
             'doentitydrops': 'entities_drop_loot', 'doweathercycle': 'weather_cycle',
             'commandblocksenabled': 'command_blocks_enabled', 'randomtickspeed': 'random_tick_speed'}


def saved_world_settings(level_dat):
    import contextlib
    import io
    from pathlib import Path
    from ..minecraft.level_dat import BedrockNBT
    if not Path(level_dat).is_file():
        return {}
    with contextlib.redirect_stdout(io.StringIO()):
        nbt = BedrockNBT.load_file(str(level_dat))
    if nbt is None:
        raise ValueError('无法读取已有存档设置，拒绝用默认配置覆盖：' + str(level_dat))
    result = {}
    for tag, key in NBT_WORLD_FIELDS.items():
        value = nbt.get_value(tag)
        if value is not None:
            result[key] = str(value) if key == 'seed' else bool(value) if key in ('cheat', 'bonus_items', 'start_with_map') else value
    rules = {}
    for tag, key in NBT_RULES.items():
        value = nbt.get_value(tag)
        if value is not None:
            rules[key] = int(value) if key == 'random_tick_speed' else bool(value)
    if rules:
        result['cheat_info'] = rules
    return result


def for_saved_world(config, level_dat):
    """Use saved state in the transient Windows launch config, not stale defaults."""
    from copy import deepcopy
    result = deepcopy(config)
    saved = saved_world_settings(level_dat)
    if saved:
        rules = saved.pop('cheat_info', {})
        result['world_info'].update(saved)
        result['world_info']['cheat_info'].update(rules)
        # always_day is a creation shortcut that would overwrite the saved cycle.
        result['world_info']['cheat_info'].pop('always_day', None)
    return result


RULE_LABELS = {
    'pvp': '玩家之间伤害', 'show_coordinates': '显示坐标', 'always_day': '始终白昼',
    'daylight_cycle': '昼夜更替', 'fire_spreads': '火焰蔓延', 'tnt_explodes': 'TNT 爆炸',
    'keep_inventory': '死亡保留物品', 'mob_spawn': '生物生成', 'natural_regeneration': '自然生命恢复',
    'mob_loot': '生物战利品', 'mob_griefing': '生物破坏', 'tile_drops': '方块掉落',
    'entities_drop_loot': '实体掉落', 'weather_cycle': '天气更替',
    'command_blocks_enabled': '命令方块', 'random_tick_speed': '随机刻速度',
    'experimental_holiday': '假日创作者实验', 'experimental_biomes': '自定义生物群系实验',
    'fancy_bubbles': '精美气泡'}
