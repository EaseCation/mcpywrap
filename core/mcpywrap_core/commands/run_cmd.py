"""Run command presentation; local lifecycle belongs to runtime services."""
import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project
from ..config import config_exists
from ..mcstudio.discovery import engine_options
from ..mcstudio.runtime_cppconfig import creation_settings, RULE_LABELS
from ..runtime.window_policy import window_options, resolve_background

WORLD_CHOICES = {
    'world_type': {'infinite': 1, 'flat': 2},
    'game_type': {'survival': 0, 'creative': 1, 'adventure': 2},
    'difficulty': {'peaceful': 0, 'easy': 1, 'normal': 2, 'hard': 3},
    'permission_level': {'visitor': 0, 'member': 1, 'operator': 2}}


def world_options(function):
    # Distinct destination names keep these out of engine discovery overrides.
    for key, label in reversed(tuple(RULE_LABELS.items())):
        flag = key.replace('_', '-')
        if key == 'random_tick_speed':
            function = click.option('--'+flag, 'world_rule_'+key, type=click.IntRange(0, 2147483647),
                                    default=None, help=label+'（仅新建实例）')(function)
        else:
            function = click.option('--'+flag+'/--no-'+flag, 'world_rule_'+key, default=None,
                                    help=label+'（仅新建实例）')(function)
    for flag, key, label in [('cheats', 'cheat', '作弊'), ('start-with-map', 'start_with_map', '初始地图'),
                             ('bonus-items', 'bonus_items', '奖励箱')]:
        function = click.option('--'+flag+'/--no-'+flag, 'world_field_'+key, default=None,
                                help=label+'（仅新建实例）')(function)
    for key, label in [('name', '世界名称'), ('seed', '种子')]:
        flag = '--world-name' if key == 'name' else '--seed'
        function = click.option(flag, 'world_field_'+key, default=None, help=label+'（仅新建实例）')(function)
    for key, values in reversed(tuple(WORLD_CHOICES.items())):
        function = click.option('--'+key.replace('_','-'), 'world_field_'+key,
                                type=click.Choice(tuple(values)), default=None,
                                help='世界设置（仅新建实例）')(function)
    return function


def take_world_options(arguments, cppconfig=None):
    info = creation_settings(cppconfig) if cppconfig else {}
    for key in tuple(arguments):
        if not key.startswith(('world_field_', 'world_rule_')):
            continue
        value = arguments.pop(key)
        if value is None:
            continue
        if key.startswith('world_rule_'):
            info.setdefault('cheat_info', {})[key[len('world_rule_'):]] = value
        else:
            field = key[len('world_field_'):]
            info[field] = WORLD_CHOICES[field][value] if field in WORLD_CHOICES else value
    return {'world_info': info} if info or cppconfig else None


@click.command(cls=OperationCommand)
@world_options
@engine_options
@window_options
@click.option("--no-gui", is_flag=True, help="不显示调试小窗；适用于 AI、脚本或纯终端操作")
@click.option("--detach", is_flag=True, help="后台运行并返回游戏会话")
@click.option('--mcs-auth', is_flag=True, help='本次单人测试或网络连接使用已登录的 MC Studio 身份')
@click.option('--cppconfig', type=click.Path(exists=True, dir_okay=False, resolve_path=True),
              help='使用 cppconfig 的 world_info 创建实例；仅与 --new 一起使用')
@click.option('--new', '-n', is_flag=True, help='创建新的游戏实例')
@click.option('--list', '-l', is_flag=True, help='列出所有可用的游戏实例')
@click.option('--delete', '-d', help='删除指定的游戏实例 (输入实例ID前缀)')
@click.option('--force', '-f', is_flag=True, help='强制删除，不提示确认')
@click.option('--clean-all', is_flag=True, help='清空所有游戏实例')
@click.option('--clients', type=click.IntRange(1, 2), default=1, show_default=True,
              help='本机玩家客户端数量；本地双客户端需在客户端 2 手动点击目标局域网卡片加入')
@click.argument('instance_prefix', required=False)
def run_cmd(new, list, delete, force, clean_all, instance_prefix, no_gui, detach, mcs_auth=False, cppconfig=None, clients=1, background=None, **engine_overrides):
    """游戏实例运行与管理
    
    可直接运行 'mcpy run' 启动最新实例，或使用选项管理实例。

    配置 [tool.mcpywrap.server] host/port 时改为网络连接；默认未认证，
    可用 --mcs-auth 显式读取 MCS 身份，单人测试同样支持此选项。
    不装配本地 Mod，不保证服务器接受连接。网络模式前台采集日志，
    Ctrl+C 结束本次网络游戏；--detach 返回可查询、操作和停止的会话。
    """
    base_dir = str(current_project())
    from ..command_context import json_output
    if clients == 2 and json_output() and not detach:
        raise click.UsageError('run --json 需要 --detach')
    if clients != 1 and (list or delete or clean_all):
        raise click.UsageError('--clients 仅用于启动游戏')
    world_config = take_world_options(engine_overrides, cppconfig)
    if world_config is not None and (not new or instance_prefix or list or delete or clean_all):
        raise click.UsageError('世界创建参数仅用于 --new，不覆盖已有实例')
    if (delete or clean_all) and non_interactive() and not force:
        raise click.UsageError("非交互删除需要 --force")
    # 检查项目是否已初始化
    if not config_exists():
        require_project()
    if mcs_auth and (list or delete or clean_all):
        raise click.UsageError('--mcs-auth 仅用于网络连接，不用于存档管理')
    from ..engines.backend import get_backend
    from ..engines.host import EngineError
    backend = get_backend()
    from ..command_context import human_interaction
    from ..dependencies import read_project
    show_debug = (human_interaction() and not (no_gui or detach or list or delete or clean_all)
                  and 'project-ui' in backend.capabilities
                  and not read_project(base_dir).get('tool', {}).get('mcpywrap', {}).get('server'))
    if show_debug:
        # Import before launching, so missing Qt cannot leave an unmanaged game.
        from ..ui.run_session import show_session_window
    options = dict(new=new, listing=list, delete=delete, force=force, clean_all=clean_all,
                   instance_prefix=instance_prefix, no_gui=True, detach=detach or show_debug,
                   mcs_auth=mcs_auth, overrides=engine_overrides, world_config=world_config,
                   background=resolve_background(background, no_gui=no_gui, detach=detach))
    def perform():
        if clients == 1:
            return backend.run(base_dir, **options)
        from ..runtime import groups
        from ..mcstudio.network import configured_target
        target = configured_target(read_project(base_dir))
        if target:
            if new or instance_prefix or world_config is not None:
                raise click.UsageError('网络联调不支持世界创建参数')
            if mcs_auth:
                raise click.UsageError('双客户端进服暂不支持双账号认证')
            return groups.start_network(base_dir, backend, target, engine_overrides,
                                        background=options['background'])
        return groups.start_local(base_dir, backend, options)
    recovered = False
    try:
        try:
            result = perform()
        except EngineError as error:
            if error.code != 'setup_required' or not backend.managed_install: raise
            from .engine_cmd import perform_install
            click.echo('首次运行：自动下载并准备本地游戏环境…', err=True)
            perform_install()
            result = perform()
    except EngineError as error:
        from ..runtime.diagnostics import diagnostic
        from .deployment_output import recover_run
        result = recover_run(base_dir, diagnostic(error)) if not show_debug else None
        if result is None:
            raise
        recovered = True
    if isinstance(result, dict) and result.get('ok') is False and not show_debug and not recovered:
        from .deployment_output import recover_run
        retry = recover_run(base_dir, result)
        if retry is not None:
            result, recovered = retry, True
    if show_debug and isinstance(result, dict) and result.get('session'):
        from ..mcstudio.sessions import show_configuration
        show_configuration(result)
        return show_session_window(base_dir, backend, result)
    if recovered and result.get('ok') is not False:
        if detach:
            from .deployment_output import show_result
            show_result(result, 'migrate')
            return
        if result.get('group'):
            from ..engines.tui import watch_group
            return watch_group(base_dir, result)
        if result.get('session') and result.get('state') in ('starting', 'running'):
            from ..engines.tui import watch_session
            from ..mcstudio.sessions import show_configuration
            show_configuration(result)
            return watch_session(base_dir, result['session'])
        from .deployment_output import show_result
        show_result(result, 'migrate')
        return
    if clients == 2 and not detach and result.get('ok') is not False:
        from ..engines.tui import watch_group
        return watch_group(base_dir, result)
    return result
