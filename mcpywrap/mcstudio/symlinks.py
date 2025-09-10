import os
import click
import ctypes
import sys
import tempfile
import json
import base64
import time
from .mcs import *
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn, TimeElapsedColumn
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout

# 强制请求管理员权限
FORCE_ADMIN = False

# 创建rich console对象
console = Console()

# 共享函数定义 - 在 symlink_helper 和 symlinks 中都可以使用
def create_symlinks(user_data_path, packs):
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

    # 用于跟踪统计信息
    total_deleted = 0
    success_count = 0
    fail_count = 0
    
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

    # 使用单一Live组件处理整个过程
    with Live(console=console, refresh_per_second=10) as live:
        # 第一阶段：清理现有链接
        live.update(Text("🧹 清理现有软链接...", style="cyan"))

        # 使用Progress组件显示清理过程
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            BarColumn(bar_width=40),
            TimeRemainingColumn(),
            console=None,  # 不直接输出到控制台
            expand=True
        )
        
        # 添加清理任务
        clean_task = progress.add_task("扫描现有链接", total=None)
        
        # 更新Live显示当前进度
        live.update(progress)

        # 清理行为包目录
        if os.path.exists(behavior_packs_dir):
            link_count = 0
            for item in os.listdir(behavior_packs_dir):
                item_path = os.path.join(behavior_packs_dir, item)
                if os.path.islink(item_path):
                    progress.update(clean_task, description=f"删除行为包链接 {item}")
                    try:
                        os.unlink(item_path)
                        link_count += 1
                    except Exception as e:
                        console.print(f"⚠️ 删除链接失败 {item}: {str(e)}", style="yellow")
            
            total_deleted += link_count
            progress.update(clean_task, description=f"已删除 {link_count} 个行为包链接")
            
        # 清理资源包目录
        if os.path.exists(resource_packs_dir):
            link_count = 0
            for item in os.listdir(resource_packs_dir):
                item_path = os.path.join(resource_packs_dir, item)
                if os.path.islink(item_path):
                    progress.update(clean_task, description=f"删除资源包链接 {item}")
                    try:
                        os.unlink(item_path)
                        link_count += 1
                    except Exception as e:
                        console.print(f"⚠️ 删除链接失败 {item}: {str(e)}", style="yellow")
            
            total_deleted += link_count
            progress.update(clean_task, description=f"清理完成")
            progress.stop()
        
        # 第二阶段：创建新链接
        live.update(Text("🔗 创建新的软链接...", style="cyan"))
        
        # 新的Progress组件用于创建链接
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            BarColumn(bar_width=40),
            TimeRemainingColumn(),
            console=None,
            expand=True
        )
        
        # 计算总任务数（行为包和资源包）
        total_tasks = 0
        for pack in packs:
            pack_data = get_pack_data(pack)
            if pack_data["behavior_pack_dir"] and os.path.exists(pack_data["behavior_pack_dir"]):
                total_tasks += 1
            if pack_data["resource_pack_dir"] and os.path.exists(pack_data["resource_pack_dir"]):
                total_tasks += 1
        
        link_task = progress.add_task("创建软链接", total=total_tasks)
        live.update(progress)
        
        # 处理所有包
        for i, pack in enumerate(packs):
            pack_data = get_pack_data(pack)
            
            # 处理行为包
            if pack_data["behavior_pack_dir"] and os.path.exists(pack_data["behavior_pack_dir"]):
                link_name = f"{os.path.basename(pack_data['behavior_pack_dir'])}_{pack_data['pkg_name']}"
                link_path = os.path.join(behavior_packs_dir, link_name)
                
                progress.update(link_task, description=f"创建行为包链接: {pack_data['pkg_name']}")

                try:
                    os.symlink(pack_data["behavior_pack_dir"], link_path)
                    behavior_links.append(link_name)
                    success_count += 1
                    # 简洁输出链接路径信息 - 源路径指向链接完整路径
                    source_path = pack_data['behavior_pack_dir'].replace('\\', '/')
                    link_full_path = link_path.replace('\\', '/')
                    console.print(f"  ✓ {source_path} → {link_full_path}", style="green")
                except Exception as e:
                    console.print(f"⚠️ 创建失败: {link_name} ({str(e)})", style="yellow")
                    fail_count += 1
                
                progress.advance(link_task)

            # 处理资源包
            if pack_data["resource_pack_dir"] and os.path.exists(pack_data["resource_pack_dir"]):
                link_name = f"{os.path.basename(pack_data['resource_pack_dir'])}_{pack_data['pkg_name']}"
                link_path = os.path.join(resource_packs_dir, link_name)
                
                progress.update(link_task, description=f"创建资源包链接: {pack_data['pkg_name']}")

                try:
                    os.symlink(pack_data["resource_pack_dir"], link_path)
                    resource_links.append(link_name)
                    success_count += 1
                    # 简洁输出链接路径信息 - 源路径指向链接完整路径
                    source_path = pack_data['resource_pack_dir'].replace('\\', '/')
                    link_full_path = link_path.replace('\\', '/')
                    console.print(f"  ✓ {source_path} → {link_full_path}", style="green")
                except Exception as e:
                    console.print(f"⚠️ 创建失败: {link_name} ({str(e)})", style="yellow")
                    fail_count += 1
                
                progress.advance(link_task)
                
        # 停止进度条
        progress.stop()
        
        # 输出最终结果（这是唯一保留在控制台上的输出）
        if fail_count == 0:
            result = Text(f"✅ Addons链接设置完成: 清理了 {total_deleted} 个旧链接，创建了 {success_count} 个新链接", style="green")
        else:
            result = Text(f"⚠️ Addons链接部分完成: 清理了 {total_deleted} 个旧链接，成功 {success_count} 个，失败 {fail_count} 个", style="yellow")
        
        live.update(result)
    
    return fail_count == 0, behavior_links, resource_links


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
    检查是否有对指定路径创建软链接的权限

    Args:
        path: 要检查的路径

    Returns:
        bool: 是否有创建软链接的权限
    """
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except:
            return False
    
    # 创建一个测试目录和一个测试链接的目标
    test_dir = os.path.join(path, '.symlink_test_dir')
    test_link = os.path.join(path, '.symlink_test')
    
    try:
        # 确保测试目录存在
        os.makedirs(test_dir, exist_ok=True)
        
        # 如果测试链接已经存在，先删除它
        if os.path.exists(test_link):
            if os.path.islink(test_link):
                os.unlink(test_link)
            else:
                os.remove(test_link)
        
        # 尝试创建一个软链接
        os.symlink(test_dir, test_link)
        
        # 验证链接是否成功创建
        has_permission = os.path.islink(test_link)
        
        # 清理测试资源
        if os.path.islink(test_link):
            os.unlink(test_link)
        if os.path.exists(test_dir):
            os.rmdir(test_dir)
            
        return has_permission
    
    except (IOError, PermissionError, OSError):
        # 删除可能创建的测试资源
        try:
            if os.path.islink(test_link):
                os.unlink(test_link)
            if os.path.exists(test_dir):
                os.rmdir(test_dir)
        except:
            pass
        return False
    except Exception:
        # 其他异常，也尝试清理
        try:
            if os.path.islink(test_link):
                os.unlink(test_link)
            if os.path.exists(test_dir):
                os.rmdir(test_dir)
        except:
            pass
        return False


def admin_global_link(script_path, packs_data, user_data_path):
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
        console.print("🔒 需要管理员权限创建[全局]软链接，正在提权...", style="yellow")
        shellExecute = ctypes.windll.shell32.ShellExecuteW
        result = shellExecute(None, "runas", sys.executable, params, None, 0)
        
        if result <= 32:  # ShellExecute返回值小于等于32表示失败
            console.print("❌ 提权失败，无法创建软链接", style="red")
            return False, [], []
        
        # 使用Live显示等待过程
        with Live("等待管理员进程完成...", console=console, refresh_per_second=4) as live:
            max_wait_time = 30  # 最多等待30秒
            start_time = time.time()
            
            while time.time() - start_time < max_wait_time:
                elapsed = time.time() - start_time
                live.update(Text(f"等待管理员进程完成... ({elapsed:.1f}秒)", style="yellow"))
                
                if os.path.exists(result_file):
                    try:
                        with open(result_file, 'r') as f:
                            result_data = json.load(f)
                        
                        # 删除临时文件
                        try:
                            os.remove(result_file)
                        except:
                            pass
                        
                        success = result_data.get("success", False)
                        behavior_links = result_data.get("behavior_links", [])
                        resource_links = result_data.get("resource_links", [])
                        
                        if success:
                            live.update(Text("✅ 管理员进程成功完成", style="green"))
                        else:
                            live.update(Text("⚠️ 管理员进程执行遇到问题", style="yellow"))
                        
                        return success, behavior_links, resource_links
                    except Exception:
                        # 文件可能还在写入，等待一下再试
                        pass
                
                # 短暂休眠避免CPU占用过高
                time.sleep(0.1)
            
            live.update(Text("⚠️ 等待管理员进程超时", style="yellow"))
        
        console.print("⚠️ 等待操作完成超时", style="yellow")
        return False, [], []
    
    except Exception as e:
        console.print(f"❌ 提权过程出错: {str(e)}", style="red")
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
        console.print("❌ 此功能仅支持Windows系统", style="red bold")
        return False, [], []
        
    try:
        # 获取MC Studio用户数据目录
        user_data_path = get_mcs_game_engine_netease_data_path()
        if not user_data_path:
            console.print("❌ 未找到MC Studio用户数据目录", style="red bold")
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
        script_path = os.path.join(current_dir, "symlink_helper_global.py")
        
        if not os.path.exists(script_path):
            console.print(f"⚠️ 辅助脚本不存在: {script_path}", style="yellow")
            return False, [], []
        
        # 以管理员权限运行辅助脚本
        return admin_global_link(script_path, simple_packs, user_data_path)
        
    except Exception as e:
        console.print(f"❌ 设置软链接失败: {str(e)}", style="red bold")
        return False, [], []
    
    
def setup_map_packs_symlinks(src_map_dir: str, level_id: str, runtime_map_dir: str):
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
        if not os.path.exists(runtime_map_dir):
            click.secho(f"❌ 运行时地图不存在: {level_id}", fg="red", bold=True)
            return False
        
        console.print("🔗 正在创建地图软链接", style="cyan")
        
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
        
        # 使用rich的Live组件来实现同行状态更新
        with Live("正在检查目录结构...", console=console, refresh_per_second=4) as live:
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
                            except Exception as e:
                                console.print(f"⚠️ 删除失败: resource_packs ({str(e)})", style="yellow")
                                return False
                    else:
                        # 删除此目录
                        live.update(Text(f"⚠️ 目标已存在且不是链接: {runtime_map_resource_packs_dir}", style="yellow"))
                        os.rmdir(runtime_map_resource_packs_dir)
                        
                links_to_create.append({
                    "source": src_map_resource_packs_dir,
                    "target": runtime_map_resource_packs_dir,
                    "type": "resource_packs"
                })
                live.update(Text(f"✓ 已准备资源包链接: {src_map_resource_packs_dir}", style="green"))
                    
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
                            except Exception as e:
                                console.print(f"⚠️ 删除失败: behavior_packs ({str(e)})", style="yellow")
                                return False
                    else:
                        live.update(Text(f"⚠️ 目标已存在且不是链接: {runtime_map_behavior_packs_dir}", style="yellow"))
                        os.rmdir(runtime_map_behavior_packs_dir)
                        
                links_to_create.append({
                    "source": src_map_behavior_packs_dir,
                    "target": runtime_map_behavior_packs_dir,
                    "type": "behavior_packs"
                })
                live.update(Text(f"✓ 已准备行为包链接: {src_map_behavior_packs_dir}", style="green"))
            
            # 如果没有需要创建的链接，直接返回成功
            if not links_to_create:
                live.update(Text("⚠️ 没有找到需要链接的资源包或行为包目录", style="yellow"))
                return True
            
            live.update(Text(f"✓ 共发现 {len(links_to_create)} 个需要创建的链接", style="green"))

        # 如果不需要管理员权限或已经是管理员，直接创建链接
        if not need_admin or is_admin():
            success = True
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[cyan]{task.description}"),
                BarColumn(bar_width=40),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                create_task = progress.add_task("正在创建链接", total=len(links_to_create))
                
                for link in links_to_create:
                    progress.update(create_task, description=f"创建链接: {os.path.basename(link['target'])}")
                    try:
                        os.symlink(link["source"], link["target"])
                        progress.advance(create_task)
                        # 简洁输出链接路径信息 - 源路径指向链接完整路径
                        source_path = link['source'].replace('\\', '/')
                        target_path = link['target'].replace('\\', '/')
                        console.print(f"  ✓ {source_path} → {target_path}", style="green")
                    except Exception as e:
                        console.print(f"❌ 创建失败: {os.path.basename(link['target'])} ({str(e)})", style="red")
                        success = False
                        
                progress.update(create_task, description="链接创建完成", completed=True)
                    
            if success:
                console.print("✅ 地图软链接设置完成！", style="green bold")
            else:
                console.print("❌ 部分链接创建失败", style="red bold")
            return success
            
        # 如果需要管理员权限
        # 获取辅助脚本路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, "symlink_helper_map.py")
        
        # 创建临时结果文件
        result_file = tempfile.mktemp(suffix='.json')
        start_marker = f"{result_file}.started"
        encoded_result = base64.b64encode(result_file.encode('utf-8')).decode('utf-8')
        
        # 确保脚本文件存在并有正确的内容
        # 这里现在不需要创建脚本，因为我们已经有单独的symlink_helper_map.py文件
        if not os.path.exists(script_path):
            console.print(f"⚠️ 辅助脚本不存在: {script_path}", style="yellow")
            return False
        
        # 执行提权操作
        console.print("🔒 需要管理员权限创建[地图]软链接，正在提权...", style="yellow")
        
        # 将链接数据编码为Base64
        encoded_links = base64.b64encode(json.dumps(links_to_create).encode('utf-8')).decode('utf-8')
        
        # 构建命令行参数
        params = f'"{script_path}" {encoded_links} {encoded_result}'
        
        # 执行提权
        shellExecute = ctypes.windll.shell32.ShellExecuteW
        result = shellExecute(None, "runas", sys.executable, params, None, 0)
        
        if result <= 32:  # ShellExecute返回值小于等于32表示失败
            console.print("❌ 提权失败，无法创建软链接", style="red")
            return False
        
        # 使用Live显示等待过程
        with Live("等待管理员进程完成...", console=console, refresh_per_second=4) as live:
            max_wait_time = 30  # 最多等待30秒
            start_time = time.time()
            script_started = False
            
            while time.time() - start_time < max_wait_time:
                elapsed = time.time() - start_time
                
                # 检查启动标记
                if not script_started and os.path.exists(start_marker):
                    script_started = True
                    live.update(Text(f"管理员进程已启动，正在执行... ({elapsed:.1f}秒)", style="cyan"))
                else:
                    live.update(Text(f"等待管理员进程完成... ({elapsed:.1f}秒)", style="yellow"))
                
                # 检查结果文件
                if os.path.exists(result_file):
                    try:
                        with open(result_file, 'r') as f:
                            result_data = json.load(f)
                        
                        # 删除临时文件
                        try:
                            os.remove(result_file)
                            if os.path.exists(start_marker):
                                os.remove(start_marker)
                        except Exception as e:
                            console.print(f"⚠️ 无法删除临时文件: {str(e)}", style="yellow")
                        
                        success = result_data.get("success", False)
                        created_links = result_data.get("created_links", [])
                        errors = result_data.get("errors", [])
                        
                        if success:
                            live.update(Text("✅ 管理员进程成功完成", style="green"))
                            console.print("✅ 地图软链接设置完成！", style="green bold")
                            for link in created_links:
                                console.print(f"  ✓ {link}", style="green")
                        else:
                            error = result_data.get("error", "详见错误列表")
                            live.update(Text(f"⚠️ 管理员进程执行遇到问题: {error}", style="yellow"))
                            console.print("❌ 地图软链接设置失败", style="red bold")
                            for err in errors:
                                console.print(f"  ✗ {err}", style="red")
                        
                        return success
                    except json.JSONDecodeError:
                        # 文件可能还在写入或格式不正确，等待一下
                        pass
                    except Exception as e:
                        console.print(f"⚠️ 读取结果文件失败: {str(e)}", style="yellow")
                
                # 短暂休眠避免CPU占用过高
                time.sleep(0.1)
                
            # 检查是否至少脚本已开始运行
            if script_started:
                live.update(Text("⚠️ 管理员进程启动了但未在规定时间内完成", style="yellow"))
            else:
                live.update(Text("⚠️ 管理员进程似乎没有启动", style="red"))
            
        console.print("⚠️ 等待操作完成超时", style="yellow")
        
        # 清理可能存在的临时文件
        try:
            if os.path.exists(result_file):
                os.remove(result_file)
            if os.path.exists(start_marker):
                os.remove(start_marker)
        except:
            pass
            
        return False
            
    except Exception as e:
        console.print(f"❌ 设置地图软链接失败: {str(e)}", style="red bold")
        return False