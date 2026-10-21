"""Explicit, preview-first local deployment recovery."""

import click

from ..command_context import OperationCommand, project_dir, remote_url


@click.group(name="deployment")
def deployment_cmd():
    """检查、修复、迁移或退役 Windows 全局部署。"""


def command(name):
    def decorate(function):
        if name != "inspect":
            function = click.option(
                "--interactive", is_flag=True, help="显示预览后在终端确认执行；默认否"
            )(function)
            function = click.option("--expect", help="脚本执行时绑定预览计划摘要")(
                function
            )
            function = click.option(
                "--apply", "apply_", is_flag=True, help="按 --expect 执行；默认只预览"
            )(function)
        if name == "retire":
            function = click.option(
                "--link",
                "links",
                multiple=True,
                type=click.Path(),
                help="仅解除明确指定的全局目录链接",
            )(function)
        if name in ("inspect", "migrate"):
            function = click.option(
                "--group", help="重试本地联调组；与 --session 互斥"
            )(function)
            function = click.option(
                "--session", help="重试失败的本地会话；与 --group 互斥"
            )(function)
            function = click.option(
                "--from",
                "from_project",
                type=click.Path(file_okay=False),
                help="旧项目目录，可仅包含运行记录",
            )(function)
        return click.command(name=name, cls=OperationCommand, local_only=True)(function)

    return decorate


def perform(
    action,
    from_project=None,
    session=None,
    group=None,
    links=(),
    apply_=False,
    expect=None,
    interactive=False,
):
    from ..command_context import human_interaction, json_output
    from ..engines.host import EngineError, describe
    from ..runtime.deployment_service import execute, preview
    from .deployment_output import confirm_and_execute, show_preview, show_result

    # Capability checks belong to execution, so nested --help works everywhere.
    if remote_url():
        raise click.UsageError("deployment 仅支持 --local；不会操作本机代替远端。")
    if describe()["backend"] != "windows":
        raise EngineError("此后端不使用 Windows 全局包部署。", "unsupported_feature")
    if interactive and (apply_ or expect):
        raise click.UsageError("--interactive 与 --apply/--expect 不能同时使用")
    if interactive and not human_interaction():
        raise click.UsageError(
            "--interactive 需要交互终端，且不能与 --json 或 --non-interactive 一起使用；脚本请先预览，再用 --apply --expect 执行。"
        )
    if expect and not apply_:
        raise click.UsageError("--expect 需要与 --apply 一起使用")
    if apply_:
        result = execute(
            project_dir(), action, from_project, session, group, links, expect
        )
        if json_output():
            return result
        show_result(result, action)
        return result if result.get("ok") is False else None
    if action == "inspect" and not (session or group) and not json_output():
        from ..runtime.deployment_service import startup_problem

        problem = startup_problem(project_dir())
        if problem:
            group = problem["details"].get("group")
            session = None if group else problem.get("session")
    value = preview(project_dir(), action, from_project, session, group, links)
    if json_output():
        return value
    show_preview(value, from_project, session, group, next_step=not interactive)
    if interactive:
        result = confirm_and_execute(value, from_project, session, group, links)
        show_result(result, action)
        return result if result.get("ok") is False else None


for name in ("inspect", "repair", "migrate", "retire"):

    def invoke(_action=name, **options):
        return perform(_action, **options)

    invoke.__doc__ = {
        "inspect": "只读检查部署证据与冲突。",
        "repair": "预览或恢复当前项目部署。",
        "migrate": "确认跨项目迁移并重试原启动。",
        "retire": "退役全局链接，保留源文件和世界。",
    }[name]
    deployment_cmd.add_command(command(name)(invoke))
