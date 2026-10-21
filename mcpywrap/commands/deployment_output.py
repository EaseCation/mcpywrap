"""Terminal recovery presentation; policy and mutations stay in the shared service."""

from collections import Counter

import click

from ..runtime.diagnostics import powershell_command
from ..utils.console import echo

KINDS = {"behavior": "行为包", "resource": "资源包"}
CHANGES = {
    "migrate": "迁移发布位置",
    "migrate_legacy": "登记历史链接",
    "rebuild": "重建缺失链接",
    "register": "补全归属登记",
    "restore_identity": "恢复部署身份",
    "recover": "恢复未完成事务",
    "retire": "解除全局链接",
}


def actions(value):
    return value.get("actions") or (value.get("details") or {}).get("actions") or []


def interactive_argv(argv):
    """Keep exact paths as arguments; never execute the displayed shell string."""
    argv = list(argv)
    if "--apply" in argv:
        argv.remove("--apply")
    if "--expect" in argv:
        index = argv.index("--expect")
        del argv[index : index + 2]
    return argv + ["--interactive"]


def conflicts_text(conflicts, details=False):
    lines = []
    if conflicts:
        counts = Counter(KINDS.get(c["kind"], c["kind"]) for c in conflicts)
        lines.append(
            "冲突范围：" + "、".join(f"{kind} {n} 个" for kind, n in counts.items())
        )
        for owner in dict.fromkeys(c.get("project") or "归属未知" for c in conflicts):
            lines.append("旧部署：" + owner)
    if details:
        for c in conflicts:
            lines.extend(
                [
                    f"  {KINDS.get(c['kind'], c['kind'])} UUID：{c['uuid']}",
                    "    全局链接：" + c["path"],
                    "    实际目标：" + c.get("target", "未知"),
                    "    当前来源：" + c.get("source", ""),
                    "    归属证据："
                    + {
                        "ownership": "持久归属登记",
                        "registry": "历史链接登记",
                        "cppconfig": "历史世界配置",
                    }.get(
                        (c.get("evidence") or {}).get("type"),
                        "已核验历史运行记录" if c.get("evidence") else "不足",
                    ),
                ]
            )
    return lines


def blockers_text(value):
    lines = []
    for issue in value.get("issues", []):
        lines.append("需处理：" + issue["message"])
        if issue.get("path"):
            lines.append("  " + issue["path"])
    for blocker in value.get("blockers", []):
        identity = blocker.get("session") or blocker.get("pid") or "身份未确认"
        state = blocker.get("state")
        reason = "无法确认是否退出" if state == "unknown" else "仍占用相关部署"
        lines.append(
            f"阻塞：{blocker.get('project') or '未知项目'}；{identity}；{reason}"
        )
    if not value.get("blockers") and value.get("issues"):
        lines.append("核对以上归属或文件问题后重新检查；不确定时保留现场。")
    if value.get("blockers"):
        lines.append("请先保存并退出上述游戏；身份仍不明时保留现场，再重新检查。")
    return lines


def format_error(value):
    """Concise terminal failure; logs/GUI keep the full diagnostic formatter."""
    details = value.get("details") or {}
    if not (actions(value) or details.get("conflicts")):
        from ..runtime.diagnostics import format_diagnostic

        return format_diagnostic(value)
    conflicts = details.get("conflicts", [])
    lines = [
        "全局包部署冲突，暂时无法启动。"
        if conflicts
        else value.get("error") or "部署操作失败"
    ]
    choices = actions(value)
    for item in choices[:1]:
        argv = item.get("argv", [])
        if "--project" in argv:
            lines.append("当前项目：" + argv[argv.index("--project") + 1])
    lines += conflicts_text(conflicts) + blockers_text(details)
    if conflicts:
        lines.append("旧部署占用了相同 UUID 的发布位置；新建或删除世界无法解除冲突。")
    elif value.get("hint"):
        lines.append(value["hint"])
    recommended = next(
        (a for a in choices if a.get("kind") in ("migrate", "repair")), None
    )
    if recommended and recommended.get("argv"):
        lines.append("下一步（只读预览）：\n" + powershell_command(recommended["argv"]))
        if recommended["kind"] == "repair" or any(
            flag in recommended["argv"] for flag in ("--session", "--group")
        ):
            lines.append("在交互终端执行该命令并加 --interactive，可预览后确认执行。")
    inspection = next((a for a in choices if a.get("kind") == "inspect"), None)
    if inspection and inspection.get("argv"):
        lines.append(
            "查看全部链接与归属证据：\n" + powershell_command(inspection["argv"])
        )
    script_log = details.get("script_log") or value.get("script_log")
    if script_log:
        lines.append("脚本日志：" + script_log)
    return "\n".join(lines)


def show_preview(value, from_project=None, session=None, group=None, next_step=True):
    action = value["action"]
    echo(
        {
            "inspect": "部署检查（只读）",
            "repair": "部署修复预览",
            "migrate": "迁移并重试预览",
            "retire": "部署退役预览",
        }[action]
    )
    echo("当前项目：" + value["project"])
    if from_project:
        echo("迁移来源：" + str(from_project))
    if session or group:
        echo(
            ("重试联调组：" if group else "重试原世界的失败会话：") + (group or session)
        )
    for line in conflicts_text(value["conflicts"], details=action == "inspect"):
        echo(line)
    for change in value["changes"]:
        echo(
            "  "
            + CHANGES.get(change["action"], change["action"])
            + "："
            + str(change.get("path") or change.get("operation_id"))
        )
    for line in blockers_text(value):
        echo(line)
    if action == "inspect":
        if not (value["conflicts"] or value["issues"] or value["blockers"]):
            echo("未发现部署冲突或占用。")
        for item in actions(value):
            if item.get("kind") in ("migrate", "repair"):
                if item["kind"] == "repair" and not (
                    value["issues"] or value["changes"] or value.get("pending")
                ):
                    continue
                echo(
                    ("迁移预览：\n" if item["kind"] == "migrate" else "修复预览：\n")
                    + powershell_command(item["argv"])
                )
                if item["kind"] == "repair" or any(
                    flag in item["argv"] for flag in ("--session", "--group")
                ):
                    echo("在终端确认执行时加 --interactive。")
                elif item["kind"] == "migrate":
                    echo(
                        "迁移重试还需指定 --session <失败会话> 或 --group <失败联调组>；普通 run --no-gui 遇到冲突时会提供对应入口。"
                    )
        return
    if action == "migrate":
        echo("只迁移以上包的发布位置，按原启动配置创建新会话；保留两边源文件和世界。")
        echo("世界就绪后完成迁移；启动失败且确认游戏退出时恢复旧部署。")
    elif action == "retire":
        echo("只解除以上全局链接，保留源文件、运行产物和世界。")
    elif action == "repair":
        echo("核验并补全当前项目的部署登记，修复以上已核验的链接或未完成事务。")
    if not value["can_apply"]:
        echo("当前不能执行，现场未修改。请先处理以上阻塞，再重新预览。")
        if action == "repair":
            for item in actions(value):
                if item.get("kind") == "migrate":
                    echo("跨项目冲突需迁移：\n" + powershell_command(item["argv"]))
    elif next_step and value.get("apply_argv"):
        echo(
            "尚未执行。终端中预览并确认：\n"
            + powershell_command(interactive_argv(value["apply_argv"]))
        )
        from ..command_context import non_interactive

        if non_interactive():
            echo("脚本执行（绑定本次预览）：\n" + value["apply_command"])


def confirm_and_execute(value, from_project=None, session=None, group=None, links=()):
    from ..engines.host import EngineError
    from ..runtime.deployment_service import execute

    if not value["can_apply"]:
        raise EngineError(
            "部署计划尚有阻塞，未执行任何变更。",
            "deployment_blocked",
            "处理上方列出的阻塞后重新预览。",
        )
    question = {
        "migrate": "确认迁移以上包并重试原世界？",
        "retire": "确认解除以上全局链接？",
        "repair": "确认执行以上部署修复？",
    }[value["action"]]
    if not click.confirm(question, default=False):
        raise EngineError("已取消，未执行部署变更。", "cancelled")
    echo("正在迁移并重试原世界…" if value["action"] == "migrate" else "正在处理部署…")
    try:
        return execute(
            value["project"],
            value["action"],
            from_project,
            session,
            group,
            links,
            value["plan_digest"],
        )
    except EngineError as error:
        if error.code == "plan_stale":
            error.hint = "重新预览并确认：\n" + powershell_command(
                interactive_argv(value["apply_argv"])
            )
        raise


def show_result(value, action):
    if value.get("ok") is False:
        return  # The command boundary renders the failure once and preserves its exit code.
    if value.get("state") == "already_applied":
        echo("该计划已完成，无需重复执行。")
    elif value.get("session") or value.get("group"):
        echo("重试已启动；迁移将在世界就绪后提交，请继续检查游戏加载结果。")
    else:
        echo(
            {"repair": "部署修复已完成。", "retire": "部署退役已完成。"}.get(
                action, "部署操作已完成。"
            )
        )
    if value.get("operation_id"):
        echo("操作记录：" + value["operation_id"])
    if value.get("group") or value.get("session"):
        flag = "--group" if value.get("group") else "--session"
        target = value.get("group") or value["session"]
        echo(("联调组：" if flag == "--group" else "新会话：") + target)
        from ..command_context import project_dir

        base = ["mcpy", "--local", "--project", str(project_dir())]
        echo("查看状态：\n" + powershell_command(base + ["status", flag, target]))
        echo("保存并停止：\n" + powershell_command(base + ["stop", flag, target]))


def recover_run(project, problem):
    """Offer one bounded migration, never infer a broader authorization."""
    from ..command_context import human_interaction

    if not human_interaction():
        return None
    candidates = [
        a for a in actions(problem) if a.get("kind") == "migrate" and a.get("from")
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    argv = candidate.get("argv", [])
    session = argv[argv.index("--session") + 1] if "--session" in argv else None
    group = argv[argv.index("--group") + 1] if "--group" in argv else None
    if not (session or group):
        return None
    from ..runtime.deployment_service import preview

    value = preview(project, "migrate", candidate["from"], session, group)
    echo("启动遇到旧项目的全局包冲突，需要确认迁移。")
    show_preview(value, candidate["from"], session, group, next_step=False)
    return confirm_and_execute(value, candidate["from"], session, group)
