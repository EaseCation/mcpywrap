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
def _create_directory_link(source, target):
    """优先符号链接；Windows 无符号链接权限时使用目录 junction。"""
    try:
        os.symlink(source, target, target_is_directory=True)
    except OSError as exc:
        if os.name != 'nt' or getattr(exc, 'winerror', None) != 1314:
            raise
        import _winapi
        _winapi.CreateJunction(os.path.abspath(source), os.path.abspath(target))


def create_symlinks(user_data_path, packs):
    """仅准备当前引用的链接，保留其他项目及运行实例使用的目录。"""
    from ..dependencies import canonical_path
    result = {'behavior': [], 'resource': []}
    planned = []
    for pack in packs:
        data = pack if isinstance(pack, dict) else vars(pack)
        for kind in result:
            source = data.get(kind + '_pack_dir')
            if not source or not os.path.isdir(source):
                continue
            name = f"{os.path.basename(source)}_{data['pkg_name']}"
            target = os.path.join(user_data_path, kind + '_packs', name)
            # 不覆盖同名的实际目录或指向其他源的链接。
            if os.path.lexists(target) and canonical_path(target) != canonical_path(source):
                console.print(f'链接名称冲突: {target}', style='red')
                return False, [], []
            planned.append((kind, source, name, target))
    created = []
    try:
        for kind, source, name, target in planned:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if not os.path.lexists(target):
                _create_directory_link(source, target)
                created.append(target)
            result[kind].append(name)
    except OSError as exc:
        # 回滚本次新建的链接，不触碰源目录及已有链接。
        for target in reversed(created):
            if os.path.islink(target):
                os.unlink(target)
            else:
                os.rmdir(target)
        console.print(f'创建目录链接失败: {exc}', style='red')
        return False, [], []
    return True, result['behavior'], result['resource']


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
    """用独立临时目录检查目录链接能力，不触碰已有内容。"""
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.mcpy-link-test-', dir=path) as probe:
            source, target = os.path.join(probe, 'source'), os.path.join(probe, 'link')
            os.mkdir(source)
            _create_directory_link(source, target)
            try:
                return os.path.samefile(source, target)
            finally:
                if os.path.islink(target):
                    os.unlink(target)
                else:
                    os.rmdir(target)
    except OSError:
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