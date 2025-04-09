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
            success, behavior_links, resource_links = create_symlinks(user_data_path, packs_data)
        else:
            # 如果导入失败，使用本地实现（这部分代码通常不会执行，作为备份）
            print("⚠️ 无法导入共享函数")
            return 1
        
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


if __name__ == "__main__":
    sys.exit(main())