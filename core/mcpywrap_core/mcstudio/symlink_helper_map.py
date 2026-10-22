# -*- coding: utf-8 -*-
import os
import json
import sys
import base64
import traceback
import time

def main():
    """辅助创建地图软链接的脚本"""
    # 立即写入启动标记文件，标明脚本已开始执行
    try:
        # 从命令行获取参数
        if len(sys.argv) != 3:
            error_msg = "参数错误: 需要2个参数 (链接信息和结果文件)"
            print(error_msg)
            sys.exit(1)

        # 从Base64编码的命令行参数中获取数据
        links_data = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
        result_file = base64.b64decode(sys.argv[2]).decode("utf-8")
        
        # 写入启动标记，确保主进程知道此脚本已启动
        start_marker = f"{result_file}.started"
        try:
            with open(start_marker, "w") as f:
                f.write("started")
                f.flush()
                os.fsync(f.fileno())  # 确保数据写入磁盘
        except Exception as e:
            print(f"无法写入启动标记: {str(e)}")
        
        success = True
        created_links = []
        errors = []
        
        # 处理每个链接
        for link in links_data:
            try:
                source = link["source"]
                target = link["target"]
                
                # 确保源目录存在
                if not os.path.exists(source):
                    error = f"源目录不存在: {source}"
                    print(error)
                    errors.append(error)
                    success = False
                    continue
                
                # 如果目标已存在，先删除
                if os.path.exists(target):
                    if os.path.islink(target):
                        os.unlink(target)
                        print(f"已删除现有链接: {target}")
                
                # 创建链接
                os.symlink(source, target, target_is_directory=True)  # 明确指定目标是目录
                print(f"链接创建成功: {target}")
                created_links.append(target)
            except Exception as e:
                error = f"链接创建失败: {str(e)}"
                print(error)
                errors.append(error)
                success = False
        
        # 写入结果文件
        result = {
            "success": success,
            "created_links": created_links,
            "errors": errors
        }
        
        # 确保结果文件目录存在
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        
        # 写入结果并确保刷新到磁盘
        with open(result_file, "w") as f:
            json.dump(result, f)
            f.flush()
            os.fsync(f.fileno())  # 强制写入磁盘
        
        # 清理启动标记
        try:
            if os.path.exists(start_marker):
                os.unlink(start_marker)
        except:
            pass
            
        print(f"结果已写入: {result_file}")
        return 0 if success else 1
        
    except Exception as e:
        print(f"执行过程中出错: {str(e)}")
        print(traceback.format_exc())
        
        # 如果有结果文件路径，也写入错误信息
        try:
            if 'result_file' in locals():
                # 确保结果文件目录存在
                os.makedirs(os.path.dirname(result_file), exist_ok=True)
                
                with open(result_file, "w") as f:
                    error_data = {"success": False, "error": str(e), "traceback": traceback.format_exc()}
                    json.dump(error_data, f)
                    f.flush()
                    os.fsync(f.fileno())  # 强制写入磁盘
        except Exception as write_error:
            print(f"写入错误信息失败: {str(write_error)}")
            
        return 1

if __name__ == "__main__":
    sys.exit(main())