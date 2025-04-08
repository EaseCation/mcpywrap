# -*- coding: utf-8 -*-
"""
辅助创建符号链接的脚本 - 以管理员权限运行
"""

import os
import json
import sys
import base64
import traceback

# 处理可能的相对导入
try:
    # 尝试导入共享函数
    from .symlinks import create_symlinks
except ImportError:
    # 当直接执行此脚本时，进行绝对导入
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from mcpywrap.mcstudio.symlinks import create_symlinks
    except ImportError:
        # 如果无法导入，定义一个空函数，稍后将检查这个函数是否可用
        create_symlinks = None


def main():
    """主函数，处理命令行参数并创建软链接"""
    # 检查命令行参数
    if len(sys.argv) != 4:
        print("参数错误: 需要3个参数 (包数据, 用户数据路径, 结果文件路径)")
        sys.exit(1)

    try:
        # 从Base64编码的命令行参数中获取数据
        packs_data = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
        user_data_path = json.loads(base64.b64decode(sys.argv[2]).decode("utf-8"))
        result_file = base64.b64decode(sys.argv[3]).decode("utf-8")
        
        # 如果可以导入共享函数，直接使用
        if create_symlinks is not None:
            # 使用共享函数创建链接，不使用click输出
            success, behavior_links, resource_links = create_symlinks(user_data_path, packs_data, use_click=False)
        else:
            # 如果导入失败，使用本地实现（这部分代码通常不会执行，作为备份）
            print("⚠️ 无法导入共享函数，使用本地实现")
            success, behavior_links, resource_links = create_links_locally(user_data_path, packs_data)
        
        # 将结果写入结果文件，供主进程读取
        result = {
            "success": success,
            "behavior_links": behavior_links,
            "resource_links": resource_links
        }
        
        with open(result_file, "w") as f:
            json.dump(result, f)
        
        return 0 if success else 1
        
    except Exception as e:
        print(f"执行过程中出错: {str(e)}")
        print(traceback.format_exc())
        
        # 写入失败结果
        try:
            with open(result_file, "w") as f:
                json.dump({"success": False, "behavior_links": [], "resource_links": []}, f)
        except:
            pass
            
        return 1


def create_links_locally(user_data_path, packs_data):
    """
    本地创建软链接的函数，当无法导入共享函数时使用
    
    Args:
        user_data_path: MC Studio用户数据目录
        packs_data: 包数据列表
        
    Returns:
        tuple: (成功状态, 行为包链接列表, 资源包链接列表)
    """
    behavior_links = []
    resource_links = []

    # 行为包和资源包目录
    behavior_packs_dir = os.path.join(user_data_path, "behavior_packs")
    resource_packs_dir = os.path.join(user_data_path, "resource_packs")

    # 确保目录存在
    os.makedirs(behavior_packs_dir, exist_ok=True)
    os.makedirs(resource_packs_dir, exist_ok=True)

    # 清空现有链接
    print("清理现有软链接...")

    try:
        if os.path.exists(behavior_packs_dir):
            for item in os.listdir(behavior_packs_dir):
                item_path = os.path.join(behavior_packs_dir, item)
                if os.path.islink(item_path):
                    os.unlink(item_path)
                    print(f"删除链接: {item}")
    except Exception as e:
        print(f"清理行为包目录失败: {str(e)}")

    try:
        if os.path.exists(resource_packs_dir):
            for item in os.listdir(resource_packs_dir):
                item_path = os.path.join(resource_packs_dir, item)
                if os.path.islink(item_path):
                    os.unlink(item_path)
                    print(f"删除链接: {item}")
    except Exception as e:
        print(f"清理资源包目录失败: {str(e)}")

    # 创建新链接
    print("创建新的软链接...")

    success = True
    for pack in packs_data:
        # 处理行为包
        if pack["behavior_pack_dir"] and os.path.exists(pack["behavior_pack_dir"]):
            link_name = f"{os.path.basename(pack['behavior_pack_dir'])}_{pack['pkg_name']}"
            link_path = os.path.join(behavior_packs_dir, link_name)

            try:
                os.symlink(pack["behavior_pack_dir"], link_path)
                print(f"行为包链接创建成功: {link_name}")
                behavior_links.append(link_name)
            except Exception as e:
                print(f"行为包链接创建失败: {str(e)}")
                success = False

        # 处理资源包
        if pack["resource_pack_dir"] and os.path.exists(pack["resource_pack_dir"]):
            link_name = f"{os.path.basename(pack['resource_pack_dir'])}_{pack['pkg_name']}"
            link_path = os.path.join(resource_packs_dir, link_name)

            try:
                os.symlink(pack["resource_pack_dir"], link_path)
                print(f"资源包链接创建成功: {link_name}")
                resource_links.append(link_name)
            except Exception as e:
                print(f"资源包链接创建失败: {str(e)}")
                success = False

    print("软链接设置完成！")
    return success, behavior_links, resource_links


if __name__ == "__main__":
    sys.exit(main())