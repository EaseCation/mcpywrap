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

