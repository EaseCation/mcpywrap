"""Local deployment coordination shared by CLI, GUI and the launch worker."""

import os
from contextlib import ExitStack, contextmanager
from pathlib import Path

from ..engines.host import EngineError
from ..utils.locks import directory_lock
from . import occupancy
from .deployment_inspection import (
    digest,
    inspect,
    permitted_receipt_issues,
    process_blockers,
    project_key,
    receipt_recovery,
    record,
    records,
    require_unblocked,
)


def global_root():
    from ..mcstudio.mcs import get_mcs_game_engine_netease_data_path

    root = get_mcs_game_engine_netease_data_path()
    if not root:
        if not os.environ.get("APPDATA"):
            raise EngineError("无法定位全局包目录：缺少 APPDATA。", "setup_required")
        root = Path(os.environ["APPDATA"]) / "MinecraftPE_Netease/games/com.netease"
    return Path(root).resolve()


def operation_projects(root, project, from_project=None):
    _, ownership = records(root)
    return (
        [project]
        + ([from_project] if from_project else [])
        + [
            r["from"]
            for r in ownership["migrations"]
            if project_key(r["to"]) == project_key(project)
        ]
    )


@contextmanager
def operation_locks(root, projects):
    """Nonblocking, ordered guards. Never reenter the parent's lifecycle lock."""
    from ..utils.paths import is_link

    store = Path(root) / ".mcpywrap"
    if is_link(store) or is_link(store / "project-locks"):
        raise EngineError("部署操作锁目录被替换为链接。", "ownership_changed")
    with ExitStack() as stack:
        for key in sorted({project_key(p) for p in projects}):
            if is_link(store / "project-locks" / digest(key)):
                raise EngineError("项目部署操作锁被替换为链接。", "ownership_changed")
            stack.enter_context(
                directory_lock(store / "project-locks" / digest(key), reentrant=True)
            )
        yield


def recovery_actions(plan, session=None, group=None):
    base = ["mcpy", "--local", "--project", plan["project"]]
    target = ["--group", group] if group else ["--session", session] if session else []
    actions = [
        {
            "label": "查看部署冲突",
            "kind": "inspect",
            "argv": base + ["deployment", "inspect"] + target,
        }
    ]
    owners = sorted({e["project"] for e in plan["conflicts"] if e.get("project")})
    for owner in owners:
        argv = base + ["deployment", "migrate", "--from", owner]
        argv += target
        actions.append(
            {
                "label": "预览从 " + owner + " 迁移",
                "kind": "migrate",
                "from": owner,
                "argv": argv,
            }
        )
    if not plan["conflicts"]:
        actions.append(
            {
                "label": "预览部署修复",
                "kind": "repair",
                "argv": base + ["deployment", "repair"],
            }
        )
    return actions


def startup_problem(project, session=None, items=None):
    """Reconstruct current guidance for old failures without rewriting history."""
    from . import instances
    from .diagnostics import diagnostic

    project = Path(project).resolve()
    if session is None:
        items = instances.list_instances(project) if items is None else items
        candidates = [
            item["last_session"] for item in items if item.get("last_session")
        ]
    else:
        candidates = [session]
    from ..mcstudio import sessions

    codes = {
        "pack_conflict",
        "link_conflict",
        "link_modified",
        "ownership_changed",
        "recovery_required",
        "deployment_relocated",
    }
    for failed_session in candidates:
        try:
            data = sessions.read(project, failed_session)
        except (OSError, ValueError):
            continue  # History may have been cleaned independently of world recipes.
        if (
            data.get("state") in ("failed", "exited")
            and data.get("mode", "local") == "local"
            and data.get("backend", "windows") == "windows"
            and (
                data.get("code") in codes
                or ("全局包" in (data.get("error") or "") and "UUID" in data["error"])
            )
        ):
            break
    else:
        return None
    plan = inspect(global_root(), project)
    if not (plan["conflicts"] or plan["issues"]):
        return None
    actions = recovery_actions(plan, failed_session)
    from . import groups

    membership = groups.membership(project, failed_session)
    if membership:
        for action in actions:
            if action["kind"] == "repair":
                continue
            argv = action["argv"]
            if "--session" in argv:
                index = argv.index("--session")
                del argv[index : index + 2]
            argv.extend(["--group", membership["group"]])
    error = EngineError(
        "上次启动因全局运行包冲突或归属问题失败，当前阻塞仍未解除。",
        "pack_conflict" if plan["conflicts"] else plan["issues"][0]["code"],
        "先预览下面的迁移或修复方案，确认后重试原世界；新建世界不会解除全局包冲突。",
        conflicts=plan["conflicts"],
        issues=plan["issues"],
        blockers=plan["blockers"],
        actions=actions,
        session=failed_session,
        level_id=data.get("level_id"),
        history_error=data.get("error"),
        group=membership["group"] if membership else None,
    )
    return dict(diagnostic(error), ok=False, session=failed_session)


def _session(project, session, group):
    from ..mcstudio import sessions

    if session and group:
        raise EngineError("只能选择会话或联调组中的一个。", "invalid_target")
    if group:
        from . import groups

        value = groups.read(project, group)
        if value["kind"] != "local" or value["backend"] != "windows":
            raise EngineError("仅支持 Windows 本地联调组迁移。", "unsupported_feature")
        return sessions.read(project, value["members"][0]["session"])
    if session:
        value = sessions.read(project, session)
        if (
            value.get("backend", "windows") != "windows"
            or value.get("mode", "local") != "local"
        ):
            raise EngineError(
                "网络会话或其他平台不使用本机全局部署。", "unsupported_feature"
            )
        from . import groups

        membership = groups.membership(project, session)
        if value.get("group") or membership:
            raise EngineError(
                "关联会话应选择整个联调组迁移。",
                "group_required",
                group=value.get("group") or membership["group"],
            )
        return value
    return None


def published_desired(plan):
    """Repair publications as they exist; preparing changed source belongs to run."""
    from ..mcstudio.deployment_links import pack_uuid
    from .deployment_inspection import manifest_digest

    desired = {}
    for key, entry in plan["registry"]["links"].items():
        if project_key(entry["project"]) == project_key(plan["project"]):
            desired[key] = dict(entry)
            if Path(entry["source"]).is_dir():
                if pack_uuid(entry["source"]) != entry["uuid"]:
                    raise EngineError(
                        "已发布包的 manifest 身份发生变化，不能通过 repair 重新认领。",
                        "deployment_modified",
                        path=entry["source"],
                    )
                desired[key]["manifest_digest"] = manifest_digest(entry["source"])
    for key, entry in plan["entries"].items():
        if entry.get("project") and project_key(entry["project"]) == project_key(
            plan["project"]
        ):
            desired.setdefault(
                key,
                {
                    "project": plan["project"],
                    "source": entry["target"],
                    "uuid": entry["uuid"],
                    "deployment": None,
                    "manifest_digest": entry.get("manifest_digest"),
                },
            )
    return desired


def preview(
    project,
    action="inspect",
    from_project=None,
    session=None,
    group=None,
    links=(),
    root=None,
):
    root = Path(root) if root is not None else global_root()
    project = Path(project).resolve()
    data = _session(project, session, group)
    plan = inspect(
        root,
        project,
        desired={} if action == "repair" else None,
        from_project=from_project,
    )
    transaction_files = sorted((root / ".mcpywrap/transactions").glob("*.json"))
    legacy_file = root / ".mcpywrap/links.transaction.json"
    if legacy_file.exists():
        transaction_files.append(legacy_file)
    has_pending = any(
        project_key((record(path) or {}).get("project", "")) == project_key(project)
        for path in transaction_files
    )
    if action == "repair" and not has_pending:
        existing = published_desired(plan)
        plan = inspect(
            root, project, desired=existing or None, from_project=from_project
        )
    pending = []
    recoverable_paths = set()
    recovery_issues = []
    for path in transaction_files:
        value = record(path)
        if value and project_key(value["project"]) == project_key(project):
            alive = occupancy.live(
                {"worker": value.get("owner"), "game": value.get("game")}
            )
            unknown = value.get("state") == "spawning" and not value.get("game")
            if action == "repair":
                if alive or unknown:
                    recovery_issues.append(
                        {
                            "code": "recovery_required",
                            "message": "事务仍在使用或游戏身份不明",
                            "operation_id": value["id"],
                        }
                    )
                else:
                    from ..mcstudio.deployment_links import ManagedLinks

                    try:
                        ManagedLinks(root, project).validate_restore(value)
                        recoverable_paths.update(
                            str(root / key)
                            for key in value.get(
                                "registry_keys", [c["key"] for c in value["changes"]]
                            )
                        )
                        if value.get("receipt"):
                            recoverable_paths.add(value["receipt"]["path"])
                    except EngineError as error:
                        recovery_issues.append(
                            {
                                "code": error.code,
                                "message": str(error),
                                "operation_id": value["id"],
                            }
                        )
            pending.append(
                {
                    "id": value.get("id"),
                    "state": value.get("state", "legacy"),
                    "legacy": path == legacy_file,
                    "owner": value.get("owner"),
                    "game": value.get("game"),
                    "session": value.get("session"),
                }
            )
    changes = []
    for e in plan["automatic"]:
        changes.append(
            {
                "action": "rebuild" if e.get("missing") else "migrate_legacy",
                "path": e["path"],
                "uuid": e["uuid"],
            }
        )
    if action == "migrate":
        if not from_project or project_key(from_project) == project_key(project):
            raise EngineError("迁移需要明确指定不同的旧项目目录。", "invalid_target")
        if not data:
            raise EngineError("迁移并重试需要 --session 或 --group。", "invalid_target")
        for e in plan["conflicts"]:
            if (
                e.get("project")
                and project_key(e["project"]) == project_key(from_project)
                and e["is_link"]
                and e["evidence"]
            ):
                changes.append(
                    {
                        "action": "migrate",
                        "path": e["path"],
                        "uuid": e["uuid"],
                        "from": e["project"],
                        "to": str(project),
                    }
                )
        selected = {c["path"] for c in changes if c["action"] == "migrate"}
        unhandled = [e for e in plan["conflicts"] if e["path"] not in selected]
        if unhandled:
            plan["issues"].append(
                {
                    "code": "pack_conflict",
                    "message": "存在不属于所选旧项目的冲突，不能扩大迁移范围。",
                }
            )
    selected = []
    if action == "retire":
        for supplied in links:
            path = Path(os.path.abspath(supplied))
            try:
                key = path.relative_to(root).as_posix()
            except ValueError:
                raise EngineError(
                    "只能选择全局包目录中的具体链接。", "invalid_target"
                ) from None
            if key not in plan["entries"]:
                raise EngineError(
                    "指定链接不存在或没有可核验 manifest。",
                    "link_modified",
                    path=str(path),
                )
            selected.append(key)
        if not selected:
            selected = [
                k
                for k, e in plan["entries"].items()
                if e.get("project")
                and project_key(e["project"]) == project_key(project)
            ]
        for key in selected:
            e = plan["entries"][key]
            if not e["is_link"] or not Path(e["target"]).is_dir():
                plan["issues"].append(
                    {
                        "code": "link_modified",
                        "path": e["path"],
                        "message": "只能退役来源存在的可恢复目录链接",
                    }
                )
            changes.append({"action": "retire", "path": e["path"], "uuid": e["uuid"]})
        affected = [project] + [
            plan["entries"][key]["project"]
            for key in selected
            if plan["entries"][key].get("project")
        ]
        plan["blockers"] = process_blockers(
            root,
            affected,
            known_projects=[e["project"] for e in plan["registry"]["links"].values()],
        )
    for value in pending:
        changes.append({"action": "recover", "operation_id": value["id"]})
    if action == "repair":
        for key, e in plan["entries"].items():
            if (
                e.get("project")
                and project_key(e["project"]) == project_key(project)
                and key not in plan["ownership"]["links"]
            ):
                changes.append(
                    {"action": "register", "path": e["path"], "uuid": e["uuid"]}
                )
    # Include exact retry intent and recovery generation, not only file-system evidence.
    group_recipe = None
    if group:
        from . import groups

        group_recipe = groups.read(project, group)
    token = digest(
        {
            "inspection": plan["plan_digest"],
            "action": action,
            "session": session,
            "group": group,
            "retry": data,
            "group_recipe": group_recipe,
            "links": sorted(selected),
            "pending": pending,
        }
    )
    argv = ["mcpy", "--local", "--project", str(project), "deployment", action]
    if from_project:
        argv += ["--from", str(Path(from_project).resolve())]
    if session:
        argv += ["--session", session]
    if group:
        argv += ["--group", group]
    for key in selected if links else ():
        argv += ["--link", str(root / key)]
    argv += ["--apply", "--expect", token]
    if receipt_recovery(plan, action, from_project) and any(
        e.get("path") == str(project / ".runtime/deployment-owner.json")
        for e in plan["issues"]
    ):
        changes.append(
            {
                "action": "restore_identity",
                "path": str(Path(project) / ".runtime/deployment-owner.json"),
            }
        )
    effective_issues = permitted_receipt_issues(plan, action, from_project)
    if action == "repair":
        effective_issues = [
            e for e in effective_issues if e.get("path") not in recoverable_paths
        ] + recovery_issues
    plan["issues"].extend(recovery_issues)
    eligible = not effective_issues and not plan["blockers"]
    if action == "repair" and plan["conflicts"]:
        eligible = False
    return {
        "state": "preview",
        "project": str(project),
        "global_root": str(root),
        "action": action,
        "plan_digest": token,
        "inspection_digest": plan["plan_digest"],
        "changes": changes,
        "conflicts": plan["conflicts"],
        "issues": plan["issues"],
        "blockers": plan["blockers"],
        "pending": pending,
        "can_apply": eligible,
        "actions": recovery_actions(plan, session, group),
        "apply_argv": argv if action != "inspect" else None,
        "apply_command": "& "
        + " ".join("'" + arg.replace("'", "''") + "'" for arg in argv)
        if action != "inspect"
        else None,
        "selected_links": selected,
        "group_expect": digest(group_recipe) if group_recipe else None,
        "related_projects": [str(project)]
        + ([str(from_project)] if from_project else [])
        + [
            plan["entries"][key]["project"]
            for key in selected
            if plan["entries"][key].get("project")
        ],
    }


def _completed(root, token):
    for path in (Path(root) / ".mcpywrap/operations").glob("*.json"):
        value = record(path)
        if (
            value
            and value.get("plan_digest") == token
            and value.get("state") == "committed"
        ):
            return {
                "state": "already_applied",
                "operation_id": value["id"],
                "session": value.get("session"),
            }


def execute(
    project,
    action,
    from_project=None,
    session=None,
    group=None,
    links=(),
    expect=None,
    root=None,
):
    if action not in ("repair", "retire", "migrate"):
        raise EngineError("该操作仅支持只读预览。", "invalid_target")
    if not expect:
        raise EngineError("执行需要 --expect 绑定预览计划。", "plan_required")
    root = Path(root) if root is not None else global_root()
    complete = _completed(root, expect)
    if complete:
        return complete
    initial = preview(project, action, from_project, session, group, links, root)
    with operation_locks(root, initial["related_projects"]):
        value = preview(project, action, from_project, session, group, links, root)
        if expect != value["plan_digest"]:
            raise EngineError(
                "部署现场或重试目标已变化，请重新预览。",
                "plan_stale",
                plan_digest=value["plan_digest"],
            )
        if not value["can_apply"]:
            raise EngineError(
                "部署计划存在阻塞，未修改现场。",
                value["issues"][0]["code"]
                if value["issues"]
                else "pack_conflict"
                if value["conflicts"]
                else "occupancy_unknown"
                if any(b["state"] == "unknown" for b in value["blockers"])
                else "deployment_in_use",
                conflicts=value["conflicts"],
                issues=value["issues"],
                blockers=value["blockers"],
            )
        if action == "migrate":
            # Worker acquires its own guards. Never wait for it while holding one.
            migration = {
                "from": str(Path(from_project).resolve()),
                "expect": value["inspection_digest"],
                "plan_digest": expect,
            }
            if group:
                migration["group_expect"] = value["group_expect"]
        else:
            migration = None
            from ..mcstudio.deployment_links import ManagedLinks
            from .deployment import Deployment

            manager = ManagedLinks(root, project)
            # Recover the whole owning deployment, not just its links.
            deployment = Deployment(project)
            with deployment.lock(), manager.lock():
                locked = preview(
                    project, action, from_project, session, group, links, root
                )
                if locked["plan_digest"] != expect:
                    raise EngineError(
                        "取得部署锁前现场已变化，请重新预览。",
                        "plan_stale",
                        plan_digest=locked["plan_digest"],
                    )
                if not locked["can_apply"]:
                    raise EngineError(
                        "取得部署锁前占用或归属已变化。",
                        "occupancy_unknown",
                        blockers=locked["blockers"],
                        issues=locked["issues"],
                    )
                deployment.preflight()
                manager.recover()
                for pending in value["pending"]:
                    if pending.get("legacy"):
                        continue
                    path = manager.transaction_path(pending["id"])
                    journal = record(path)
                    if journal:
                        if (
                            occupancy.live(
                                {
                                    "worker": journal.get("owner"),
                                    "game": journal.get("game"),
                                }
                            )
                            or journal.get("state") == "spawning"
                        ):
                            raise EngineError(
                                "事务仍在使用或游戏身份不明。", "recovery_required"
                            )
                        manager.restore(journal)
                if action == "retire":
                    _, journal = (
                        manager._publish(
                            {},
                            retiring=value["selected_links"],
                            explicit=bool(links),
                            plan_digest=expect,
                        )
                        if value["selected_links"]
                        else ({}, None)
                    )
                else:
                    current = inspect(root, project, desired={})
                    desired = published_desired(current)
                    _, journal = manager._publish(
                        desired, repair_receipt=True, plan_digest=expect
                    )
                if journal:
                    return {
                        "state": "completed",
                        "operation_id": journal["id"],
                        "changes": value["changes"],
                    }
                return {"state": "unchanged", "changes": []}
    # A fresh launch owns migration + publication until the world-ready commit.
    from . import groups

    if group:
        return groups.restart(project, group=group, migration=migration)
    data = _session(project, session, None)
    if occupancy.live(data):
        raise EngineError("原会话仍在运行，请先保存退出。", "deployment_in_use")
    from .windows import run

    overrides = dict(data.get("engine_overrides") or {})
    selected = (data.get("launch") or {}).get("engine") or {}
    for option, field in (
        ("engine_version", "version"),
        ("game_executable_path", "executable"),
        ("mcs_download_path", "download_dir"),
    ):
        if selected.get(field):
            overrides[option] = selected[field]
    return run(
        project,
        instance_prefix=data["level_id"],
        overrides=overrides,
        mcs_auth=bool(data.get("mcs_auth")),
        world_config=None,
        detach=True,
        no_gui=True,
        background=data.get("background", False),
        migration=migration,
    )


def preserve_before_delete(project, root=None):
    """Persist legacy evidence before its last world recipe is removed."""
    from ..mcstudio.deployment_links import ManagedLinks

    root = Path(root) if root is not None else global_root()
    manager = ManagedLinks(root, project)
    with manager.lock():
        plan = inspect(root, project, desired={})
        if plan["issues"]:
            require_unblocked(plan)
        links = dict(plan["registry"]["links"])
        for key, e in plan["entries"].items():
            if e.get("project") and project_key(e["project"]) == project_key(project):
                links.setdefault(
                    key,
                    {
                        "project": str(Path(project).resolve()),
                        "source": e["target"],
                        "uuid": e["uuid"],
                        "deployment": None,
                    },
                )
        if links != plan["registry"]["links"]:
            # No links change; the same transaction captures the evidence in both indexes.
            desired = {
                k: e
                for k, e in links.items()
                if project_key(e["project"]) == project_key(project)
            }
            manager._publish(desired)
