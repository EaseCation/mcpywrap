import os
import click
import ctypes
import sys
import tempfile
import json
import base64
import time
from .mcs import *

from ..config import get_project_type

# 强制请求管理员权限
FORCE_ADMIN = True


# 共享函数定义 - 在 symlink_helper 和 symlinks 中都可以使用
def create_symlinks(user_data_path, packs, use_click=True):
    """
    在指定目录下为行为包和资源包创建软链接
    
    Args:
        user_data_path: MC Studio用户数据目录
        packs: 行为包和资源包列表
        use_click: 是否使用click库进行输出，子进程中会设置为False
        
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

    # 打印函数，根据是否使用click选择不同的输出方式
    def print_msg(message, color=None, bold=False):
        if use_click:
            click.secho(message, fg=color, bold=bold)
        else:
            print(message)

    # 清空现有链接
    print_msg("🧹 清理现有软链接...", color="cyan")

    # 清理行为包目录
    if os.path.exists(behavior_packs_dir):
        for item in os.listdir(behavior_packs_dir):
            item_path = os.path.join(behavior_packs_dir, item)
            if os.path.islink(item_path):
                try:
                    os.unlink(item_path)
                    print_msg(f"🗑️ 删除链接: {item}", color="cyan")
                except Exception as e:
                    print_msg(f"⚠️ 删除链接失败 {item}: {str(e)}", color="yellow")

    # 清理资源包目录
    if os.path.exists(resource_packs_dir):
        for item in os.listdir(resource_packs_dir):
            item_path = os.path.join(resource_packs_dir, item)
            if os.path.islink(item_path):
                try:
                    os.unlink(item_path)
                    print_msg(f"🗑️ 删除链接: {item}", color="cyan")
                except Exception as e:
                    print_msg(f"⚠️ 删除链接失败 {item}: {str(e)}", color="yellow")

    # 创建新链接
    print_msg("🔗 创建新的软链接...", color="cyan")

    # 处理包数据格式的统一转换函数
    def get_pack_data(pack):
        """从不同格式的pack对象中提取数据"""
        if isinstance(pack, dict):
            # 如果是字典格式，直接使用
            return {
                "behavior_pack_dir": pack.get("behavior_pack_dir"),
                "resource_pack_dir": pack.get("resource_pack_dir"),
                "pkg_name": pack.get("pkg_name")
            }
        else:
            # 如果是对象格式，从属性中获取
            return {
                "behavior_pack_dir": getattr(pack, "behavior_pack_dir", None),
                "resource_pack_dir": getattr(pack, "resource_pack_dir", None),
                "pkg_name": getattr(pack, "pkg_name", "unknown")
            }

    for pack in packs:
        pack_data = get_pack_data(pack)
        
        # 处理行为包
        if pack_data["behavior_pack_dir"] and os.path.exists(pack_data["behavior_pack_dir"]):
            link_name = f"{os.path.basename(pack_data['behavior_pack_dir'])}_{pack_data['pkg_name']}"
            link_path = os.path.join(behavior_packs_dir, link_name)

            try:
                os.symlink(pack_data["behavior_pack_dir"], link_path)
                print_msg(f"✅ 行为包链接创建成功: {link_name}", color="green")
                behavior_links.append(link_name)
            except Exception as e:
                print_msg(f"⚠️ 行为包链接创建失败: {str(e)}", color="yellow")

        # 处理资源包
        if pack_data["resource_pack_dir"] and os.path.exists(pack_data["resource_pack_dir"]):
            link_name = f"{os.path.basename(pack_data['resource_pack_dir'])}_{pack_data['pkg_name']}"
            link_path = os.path.join(resource_packs_dir, link_name)

            try:
                os.symlink(pack_data["resource_pack_dir"], link_path)
                print_msg(f"✅ 资源包链接创建成功: {link_name}", color="green")
                resource_links.append(link_name)
            except Exception as e:
                print_msg(f"⚠️ 资源包链接创建失败: {str(e)}", color="yellow")

    print_msg("✅ 软链接设置完成！", color="green", bold=True)
    return True, behavior_links, resource_links


def is_admin():
    """
    检查当前程序是否以管理员权限运行

    Returns:
        bool: 是否具有管理员权限
    """
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


def has_write_permission(path):
    """
    检查是否有对指定路径的写入权限

    Args:
        path: 要检查的路径

    Returns:
        bool: 是否有写入权限
    """
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except:
            return False
    
    test_file = os.path.join(path, '.write_permission_test')
    try:
        # 尝试创建文件
        with open(test_file, 'w') as f:
            f.write('test')
        # 如果成功创建，删除测试文件
        os.remove(test_file)
        return True
    except (IOError, PermissionError):
        return False
    except Exception:
        # 其他异常
        return False


def run_as_admin(script_path, packs_data, user_data_path):
    """
    以管理员权限运行脚本
    
    Args:
        script_path: 脚本路径
        packs_data: 包数据
        user_data_path: 用户数据路径
        
    Returns:
        tuple: (成功状态, 行为包链接列表, 资源包链接列表)
    """
    try:
        # 创建临时结果文件
        result_file = tempfile.mktemp(suffix='.json')
        
        # 将数据编码为Base64
        encoded_packs = base64.b64encode(json.dumps(packs_data).encode('utf-8')).decode('utf-8')
        encoded_path = base64.b64encode(json.dumps(user_data_path).encode('utf-8')).decode('utf-8')
        encoded_result = base64.b64encode(result_file.encode('utf-8')).decode('utf-8')
        
        # 构建命令行参数
        params = f'"{script_path}" {encoded_packs} {encoded_path} {encoded_result}'
        
        # 执行提权操作
        click.secho("🔒 需要管理员权限创建软链接，正在提权...", fg="yellow")
        shellExecute = ctypes.windll.shell32.ShellExecuteW
        result = shellExecute(None, "runas", sys.executable, params, None, 0)
        
        if result <= 32:  # ShellExecute返回值小于等于32表示失败
            click.secho("❌ 提权失败，无法创建软链接", fg="red")
            return False, [], []
        
        # 等待脚本执行完成
        max_wait_time = 30  # 最多等待30秒
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            if os.path.exists(result_file):
                try:
                    with open(result_file, 'r') as f:
                        result_data = json.load(f)
                    
                    # 删除临时文件
                    try:
                        os.remove(result_file)
                    except:
                        pass
                    
                    return (
                        result_data.get("success", False),
                        result_data.get("behavior_links", []),
                        result_data.get("resource_links", [])
                    )
                except Exception:
                    # 文件可能还在写入，等待一下再试
                    pass
            
            # 短暂休眠避免CPU占用过高
            time.sleep(0.1)
        
        click.secho("⚠️ 等待操作完成超时", fg="yellow")
        return False, [], []
    
    except Exception as e:
        click.secho(f"❌ 提权过程出错: {str(e)}", fg="red")
        return False, [], []


def setup_global_addons_symlinks(packs: list):
    """
    在MC Studio用户数据目录下为行为包和资源包创建软链接
    
    Args:
        packs: 行为包和资源包列表
        
    Returns:
        tuple: (成功状态, 行为包链接列表, 资源包链接列表)
    """
    if not is_windows():
        click.secho("❌ 此功能仅支持Windows系统", fg="red", bold=True)
        return False, [], []
        
    try:
        # 获取MC Studio用户数据目录
        user_data_path = get_mcs_game_engine_netease_data_path()
        if not user_data_path:
            click.secho("❌ 未找到MC Studio用户数据目录", fg="red", bold=True)
            return False, [], []
            
        # 判断是否需要管理员权限
        behavior_packs_dir = os.path.join(user_data_path, "behavior_packs")
        resource_packs_dir = os.path.join(user_data_path, "resource_packs")
        
        need_admin = FORCE_ADMIN or (not (has_write_permission(behavior_packs_dir) and has_write_permission(resource_packs_dir)))
        
        # 如果不需要管理员权限或已经是管理员，直接创建软链接
        if not need_admin or is_admin():
            return create_symlinks(user_data_path, packs)
            
        # 将包对象转换为简单字典
        simple_packs = []
        for pack in packs:
            simple_pack = {
                "behavior_pack_dir": pack.behavior_pack_dir if hasattr(pack, 'behavior_pack_dir') else None,
                "resource_pack_dir": pack.resource_pack_dir if hasattr(pack, 'resource_pack_dir') else None,
                "pkg_name": pack.pkg_name
            }
            simple_packs.append(simple_pack)
        
        # 获取辅助脚本路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, "symlink_helper.py")
        
        if not os.path.exists(script_path):
            click.secho(f"⚠️ 辅助脚本不存在: {script_path}", fg="yellow")
            return False, [], []
        
        # 以管理员权限运行辅助脚本
        return run_as_admin(script_path, simple_packs, user_data_path)
        
    except Exception as e:
        click.secho(f"❌ 设置软链接失败: {str(e)}", fg="red", bold=True)
        return False, [], []
    
    
def setup_map_packs_symlinks(src_map_dir: str, level_id: str):
    """
    为地图创建资源包和行为包的软链接
    
    Args:
        src_map_dir: 源地图目录
        level_id: 运行时地图ID
        
    Returns:
        bool: 操作是否成功
    """
    if not is_windows():
        click.secho("❌ 此功能仅支持Windows系统", fg="red", bold=True)
        return False
        
    try:
        # 获取MC Studio用户数据目录
        user_data_path = get_mcs_game_engine_data_path()
        if not user_data_path:
            click.secho("❌ 未找到MC Studio用户数据目录", fg="red", bold=True)
            return False
            
        # 确保源地图目录存在
        if not os.path.exists(src_map_dir):
            click.secho(f"❌ 源地图目录不存在: {src_map_dir}", fg="red", bold=True)
            return False
            
        # 运行时地图目录
        runtime_map_dir = os.path.join(user_data_path, "minecraftWorlds", level_id)
        if not os.path.exists(runtime_map_dir):
            click.secho(f"❌ 运行时地图不存在: {level_id}", fg="red", bold=True)
            return False
        
        # 源地图资源包和行为包目录
        src_map_resource_packs_dir = os.path.join(src_map_dir, "resource_packs")
        src_map_behavior_packs_dir = os.path.join(src_map_dir, "behavior_packs")
        
        # 运行时地图资源包和行为包目录
        runtime_map_resource_packs_dir = os.path.join(runtime_map_dir, "resource_packs")
        runtime_map_behavior_packs_dir = os.path.join(runtime_map_dir, "behavior_packs")
        
        # 判断是否需要管理员权限
        need_admin = FORCE_ADMIN or (
            (os.path.exists(src_map_dir) and not has_write_permission(src_map_dir))
        )
        
        # 准备需要创建的链接信息
        links_to_create = []
        
        # 检查资源包目录
        if os.path.exists(src_map_resource_packs_dir):
            # 确保目标目录存在
            os.makedirs(os.path.dirname(runtime_map_resource_packs_dir), exist_ok=True)
            
            # 如果目标已存在，需要先删除
            if os.path.exists(runtime_map_resource_packs_dir):
                if os.path.islink(runtime_map_resource_packs_dir):
                    if not need_admin or is_admin():
                        try:
                            os.unlink(runtime_map_resource_packs_dir)
                            click.secho(f"🗑️ 删除现有链接: {runtime_map_resource_packs_dir}", color="cyan")
                        except Exception as e:
                            click.secho(f"⚠️ 删除链接失败: {str(e)}", color="yellow")
                            return False
                else:
                    click.secho(f"⚠️ 目标已存在且不是链接: {runtime_map_resource_packs_dir}", color="yellow")
                    return False
                    
            links_to_create.append({
                "source": src_map_resource_packs_dir,
                "target": runtime_map_resource_packs_dir,
                "type": "resource_packs"
            })
                
        # 检查行为包目录
        if os.path.exists(src_map_behavior_packs_dir):
            # 确保目标目录存在
            os.makedirs(os.path.dirname(runtime_map_behavior_packs_dir), exist_ok=True)
            
            # 如果目标已存在，需要先删除
            if os.path.exists(runtime_map_behavior_packs_dir):
                if os.path.islink(runtime_map_behavior_packs_dir):
                    if not need_admin or is_admin():
                        try:
                            os.unlink(runtime_map_behavior_packs_dir)
                            click.secho(f"🗑️ 删除现有链接: {runtime_map_behavior_packs_dir}", color="cyan")
                        except Exception as e:
                            click.secho(f"⚠️ 删除链接失败: {str(e)}", color="yellow")
                            return False
                else:
                    click.secho(f"⚠️ 目标已存在且不是链接: {runtime_map_behavior_packs_dir}", color="yellow")
                    return False
                    
            links_to_create.append({
                "source": src_map_behavior_packs_dir,
                "target": runtime_map_behavior_packs_dir,
                "type": "behavior_packs"
            })
            
        # 如果没有需要创建的链接，直接返回成功
        if not links_to_create:
            click.secho("⚠️ 没有找到需要链接的资源包或行为包目录", color="yellow")
            return True
            
        # 如果不需要管理员权限或已经是管理员，直接创建链接
        if not need_admin or is_admin():
            success = True
            for link in links_to_create:
                try:
                    os.symlink(link["source"], link["target"])
                    click.secho(f"✅ 链接创建成功: {link['target']} -> {link['source']}", color="green")
                except Exception as e:
                    click.secho(f"❌ 链接创建失败: {str(e)}", color="red")
                    success = False
                    
            if success:
                click.secho("✅ 地图软链接设置完成！", color="green", bold=True)
            return success
            
        # 如果需要管理员权限
        # 获取辅助脚本路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, "symlink_helper_map.py")
        
        # 创建辅助脚本文件
        with open(script_path, "w") as f:
            f.write("""# -*- coding: utf-8 -*-
import os
import json
import sys
import base64
import traceback

def main():
    \"\"\"辅助创建地图软链接的脚本\"\"\"
    # 检查命令行参数
    if len(sys.argv) != 2:
        print("参数错误: 需要1个参数 (链接信息)")
        sys.exit(1)

    try:
        # 从Base64编码的命令行参数中获取数据
        links_data = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
        
        success = True
        for link in links_data:
            try:
                # 如果目标已存在，先删除
                if os.path.exists(link["target"]):
                    if os.path.islink(link["target"]):
                        os.unlink(link["target"])
                
                # 创建链接
                os.symlink(link["source"], link["target"])
                print(f"链接创建成功: {link['target']}")
            except Exception as e:
                print(f"链接创建失败: {str(e)}")
                success = False
                
        return 0 if success else 1
        
    except Exception as e:
        print(f"执行过程中出错: {str(e)}")
        print(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
""")
        
        # 执行提权操作
        click.secho("🔒 需要管理员权限创建软链接，正在提权...", fg="yellow")
        
        # 将链接数据编码为Base64
        encoded_links = base64.b64encode(json.dumps(links_to_create).encode('utf-8')).decode('utf-8')
        
        # 构建命令行参数
        params = f'"{script_path}" {encoded_links}'
        
        # 执行提权
        shellExecute = ctypes.windll.shell32.ShellExecuteW
        result = shellExecute(None, "runas", sys.executable, params, None, 0)
        
        if result <= 32:  # ShellExecute返回值小于等于32表示失败
            click.secho("❌ 提权失败，无法创建软链接", fg="red")
            return False
            
        click.secho("✅ 地图软链接设置完成！", color="green", bold=True)
        return True
        
    except Exception as e:
        click.secho(f"❌ 设置地图软链接失败: {str(e)}", fg="red", bold=True)
        return False