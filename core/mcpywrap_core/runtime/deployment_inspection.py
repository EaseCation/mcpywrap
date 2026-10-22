"""Read-only deployment evidence and deterministic policy. No locks or writes."""

import hashlib
import json
import os
from pathlib import Path

from ..engines.host import EngineError
from ..utils.paths import is_link
from . import occupancy, storage

KINDS = ("behavior", "resource")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def record(path, default=None):
    path = Path(path)
    if is_link(path):
        raise EngineError("部署登记文件被替换为链接：" + str(path), "ownership_changed")
    try:
        value = storage.read(path, default)
    except (ValueError, OSError) as exc:
        raise EngineError(
            "无法读取部署登记：" + str(path), "recovery_required"
        ) from exc
    if value is not None and not isinstance(value, dict):
        raise EngineError("部署登记格式无效：" + str(path), "recovery_required")
    return value


def owner_path(project):
    path = Path(project) / ".runtime/deployment-owner.json"
    if is_link(path.parent) or is_link(path):
        raise EngineError("项目部署登记被替换为链接：" + str(path), "ownership_changed")
    return path


def project_key(project):
    return occupancy.path_key(project)


def link_key(project, kind, identity):
    prefix = hashlib.sha256(project_key(project).encode()).hexdigest()[:12]
    return kind + "_packs/mcpy_" + prefix + "_" + kind + "_" + identity.replace("-", "")


def manifest_digest(source):
    for name in ("manifest.json", "pack_manifest.json"):
        path = Path(source) / name
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    return None


def desired_packs(project, packs, deployment=None):
    from ..mcstudio.deployment_links import pack_uuid

    desired = {}
    for pack in packs:
        for kind in KINDS:
            source = getattr(pack, kind + "_pack_dir", None)
            if not source or not Path(source).is_dir():
                continue
            identity = pack_uuid(source)
            if not identity:
                continue
            key = link_key(project, kind, identity)
            entry = {
                "project": str(Path(project).resolve()),
                "source": str(Path(source).resolve()),
                "uuid": identity,
                "deployment": deployment,
                "manifest_digest": manifest_digest(source),
            }
            if key in desired and desired[key]["source"] != entry["source"]:
                raise EngineError("待发布包包含重复 UUID：" + identity, "pack_conflict")
            desired[key] = entry
    return desired


def project_packs(project):
    """Read manifests and installed map dependencies; never install or run hooks."""
    from ..dependencies import DependencyService, read_project
    from ..mcstudio.deployment_links import pack_uuid

    project = Path(project).resolve()
    config = read_project(project) if (project / "pyproject.toml").is_file() else {}
    is_map = config.get("tool", {}).get("mcpywrap", {}).get("project_type") == "map"
    desired = {}
    sources = []
    if is_map:
        manager = DependencyService(project).resolve(config)
        for pack in manager.get_all_dependencies().values():
            for kind in KINDS:
                folder = getattr(pack, kind + "_pack_dir", None)
                if folder:
                    sources.append((kind, Path(folder)))
        for kind in KINDS:
            parent = project / (kind + "_packs")
            for source in sorted(parent.iterdir()) if parent.is_dir() else ():
                sources.append((kind, source))
    elif (project / "pyproject.toml").is_file():
        manager = DependencyService(project).resolve(config)
        packs = list(manager.get_all_dependencies().values()) + [
            manager.root_node.addon_pack
        ]
        for kind in KINDS:
            folder = next(
                (
                    getattr(pack, kind + "_pack_dir")
                    for pack in reversed(packs)
                    if getattr(pack, kind + "_pack_dir", None)
                ),
                None,
            )
            if folder:
                sources.append((kind, Path(folder)))
    else:
        for kind, prefix in (
            ("behavior", ("behavior_pack", "BehaviorPack")),
            ("resource", ("resource_pack", "ResourcePack")),
        ):
            matches = (
                [
                    p
                    for p in project.iterdir()
                    if p.is_dir() and p.name.startswith(prefix)
                ]
                if project.is_dir()
                else []
            )
            if len(matches) > 1:
                raise EngineError(
                    "项目包含多个同类型包，无法确定部署身份。", "invalid_manifest"
                )
            if matches:
                sources.append((kind, matches[0]))
    for kind, source in sources:
        identity = pack_uuid(source)
        if identity:
            target = (
                project / ".mcpy/runtime/assembled" / (kind + "_pack")
                if not is_map
                else project / ".mcpy/runtime/assembled" / (kind + "_packs") / identity
            )
            desired[link_key(project, kind, identity)] = {
                "project": str(project),
                "source": str(target.resolve()),
                "uuid": identity,
                "deployment": None,
                "manifest_digest": manifest_digest(source),
            }
    return desired


def migration_origin(plan, entry):
    """Confirmed paths alone must not grant a replacement owner permission."""
    project = entry["project"]
    indexed = plan["ownership"]["owners"].get(project_key(project))
    receipt = record(owner_path(project))
    if indexed and (
        (not receipt and Path(project).exists())
        or (receipt and indexed.get("id") != receipt.get("id"))
    ):
        return None
    owner = indexed or receipt
    if owner and project_key(owner.get("project", "")) != project_key(project):
        return None
    value = {"project": project_key(project), "target": project_key(entry["target"])}
    if owner:
        value["owner_id"] = owner["id"]
    else:
        value["evidence"] = entry["evidence"]
    return value


def legacy_evidence(project, kind, path):
    """A real link into this project plus an independent historical reference."""
    path, project = Path(path), Path(project).resolve()
    if not is_link(path) or not path.is_dir():
        return None
    try:
        path.resolve().relative_to(project)
    except ValueError:
        return None
    runtime = project / ".runtime"
    configs = sorted(runtime.glob("*.cppconfig")) + sorted(
        (runtime / "sessions").glob("*/*.cppconfig")
    )
    for config in configs:
        try:
            value = storage.read(config, {})
        except (OSError, ValueError):
            continue
        info = value.get("world_info") if isinstance(value, dict) else None
        refs = info.get(kind + "_packs") if isinstance(info, dict) else None
        if isinstance(refs, list) and path.name in refs:
            return {"type": "cppconfig", "path": str(config), "digest": digest(value)}
    return None


def candidates(source, projects):
    result = {project_key(p): str(Path(p).resolve()) for p in projects if p}
    for parent in (Path(source), *Path(source).parents):
        if (parent / ".runtime").is_dir():
            result[project_key(parent)] = str(parent.resolve())
    return list(result.values())


def validate_key(key):
    parts = Path(key).parts
    if (
        len(parts) != 2
        or parts[0] not in ("behavior_packs", "resource_packs")
        or parts[1] in (".", "..")
    ):
        raise EngineError("全局链接登记路径无效。", "recovery_required")


def records(root):
    root = Path(root)
    for path in (
        root,
        root / ".mcpywrap",
        root / "behavior_packs",
        root / "resource_packs",
        root / ".mcpywrap/transactions",
        root / ".mcpywrap/operations",
        root / ".mcpywrap/project-locks",
    ):
        if is_link(path):
            raise EngineError(
                "全局部署目录被替换为链接：" + str(path), "ownership_changed"
            )
    links = record(root / ".mcpywrap/links.json", {"schema_version": 1, "links": {}})
    ownership = record(
        root / ".mcpywrap/ownership.json",
        {"schema_version": 1, "owners": {}, "links": {}, "migrations": []},
    )
    if not isinstance(links.get("links"), dict) or not all(
        isinstance(ownership.get(k), t)
        for k, t in (("owners", dict), ("links", dict), ("migrations", list))
    ):
        raise EngineError("全局部署登记格式无效。", "recovery_required")
    for key in set(links["links"]) | set(ownership["links"]):
        validate_key(key)
    return links, ownership


def process_blockers(root, projects, exclude=(), known_projects=()):
    """Unknown game processes are blockers, never a reason to kill by name."""
    import psutil

    known, blockers = set(), []
    affected = {project_key(p) for p in projects if p}
    for project in sorted({str(p) for p in list(projects) + list(known_projects) if p}):
        for path in sorted(
            (Path(project) / ".runtime/sessions").glob("*/session.json")
        ):
            value = record(path)
            if not value:
                continue
            if value.get("game"):
                # PID reuse is checked by occupancy.live, not by PID alone.
                from ..mcstudio.processes import observed_process

                if observed_process(value["game"]):
                    known.add(value["game"]["pid"])
            if value.get("session") in exclude:
                continue
            if project_key(project) in affected and (
                occupancy.live(value) or occupancy.launch_identity_missing(value)
            ):
                blockers.append(
                    {
                        "project": str(project),
                        "session": value.get("session"),
                        "state": "active" if occupancy.live(value) else "unknown",
                    }
                )
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if (
                process.info["name"] or ""
            ).lower() == "minecraft.windows.exe" and process.pid not in known:
                try:
                    environment = process.environ()
                    appdata = environment.get("APPDATA")
                    profile = environment.get("USERPROFILE")
                    if (
                        isinstance(appdata, str)
                        and appdata
                        and isinstance(profile, str)
                        and profile
                        and project_key(appdata)
                        == project_key(Path(profile) / "AppData/Roaming")
                        and project_key(
                            Path(appdata) / "MinecraftPE_Netease/games/com.netease"
                        )
                        != project_key(root)
                    ):
                        continue
                except (psutil.Error, OSError, ValueError, NotImplementedError):
                    pass
                blockers.append(
                    {
                        "pid": process.pid,
                        "state": "unknown",
                        "reason": "游戏进程没有可核验的会话归属",
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return blockers


def inspect(root, project, desired=None, from_project=None, exclude=()):
    from ..mcstudio.deployment_links import pack_uuid

    root, project = Path(root).resolve(), str(Path(project).resolve())
    desired = project_packs(project) if desired is None else desired
    registry, ownership = records(root)
    receipt_file = owner_path(project)
    receipt_raw = None
    issues, conflicts, automatic = [], [], []
    try:
        receipt = record(receipt_file)
    except EngineError:
        if is_link(receipt_file):
            raise
        import base64

        receipt_raw = base64.b64encode(receipt_file.read_bytes()).decode("ascii")
        receipt = None
        issues.append(
            {
                "code": "ownership_changed",
                "path": str(receipt_file),
                "message": "项目部署身份文件损坏，需要确认重建",
            }
        )
    if receipt and project_key(receipt.get("project", "")) != project_key(project):
        issues.append(
            {
                "code": "ownership_changed",
                "path": str(owner_path(project)),
                "message": "项目路径与部署身份绑定不符，需要显式迁移",
            }
        )
    registered_owner = ownership["owners"].get(project_key(project))
    if registered_owner and (
        not receipt or registered_owner.get("id") != receipt.get("id")
    ):
        issues.append(
            {
                "code": "ownership_changed",
                "path": str(owner_path(project)),
                "message": "项目部署身份缺失或与全局记录不一致",
            }
        )
    all_projects = [project, from_project] + [
        e.get("project") for e in registry["links"].values()
    ]
    entries = {}
    for kind in KINDS:
        folder = root / (kind + "_packs")
        for path in sorted(folder.iterdir()) if folder.is_dir() else ():
            key = path.relative_to(root).as_posix()
            if not path.is_dir():
                continue
            try:
                identity = pack_uuid(path)
            except EngineError:
                if key in registry["links"]:
                    issues.append(
                        {
                            "code": "invalid_manifest",
                            "path": str(path),
                            "message": "登记链接的 manifest 无效",
                        }
                    )
                continue
            old = registry["links"].get(key)
            if (
                old
                and (
                    not is_link(path) or project_key(path) != project_key(old["source"])
                )
                and (
                    project_key(old["project"]) == project_key(project)
                    or identity in {e["uuid"] for e in desired.values()}
                )
            ):
                issues.append(
                    {
                        "code": "link_modified",
                        "path": str(path),
                        "message": "登记链接实际目标已变化",
                    }
                )
            if not identity:
                continue
            source = str(path.resolve())
            owner = old.get("project") if old else None
            evidence = {"type": "registry", "entry": old} if old else None
            if not old and is_link(path):
                matches = [
                    (p, legacy_evidence(p, kind, path))
                    for p in candidates(source, all_projects)
                ]
                matches = [(p, e) for p, e in matches if e]
                if len(matches) == 1:
                    owner, evidence = matches[0]
            durable = ownership["links"].get(key)
            if durable:
                if old != durable.get("entry") and (
                    identity in {e["uuid"] for e in desired.values()}
                    or project_key(durable["entry"]["project"]) == project_key(project)
                ):
                    issues.append(
                        {
                            "code": "ownership_changed",
                            "path": str(path),
                            "message": "链接表与持久归属不一致",
                        }
                    )
                owner, evidence = (
                    durable["entry"]["project"],
                    {"type": "ownership", "owner_id": durable["owner_id"]},
                )
            entry = {
                "kind": kind,
                "uuid": identity,
                "path": str(path),
                "key": key,
                "target": source,
                "project": owner,
                "evidence": evidence,
                "is_link": is_link(path),
                "manifest_digest": manifest_digest(path),
            }
            entries[key] = entry
            wanted = next(
                (
                    e
                    for k, e in desired.items()
                    if k.startswith(kind + "_packs/") and e["uuid"] == identity
                ),
                None,
            )
            if wanted:
                entry = dict(entry, source=wanted["source"])
                own = owner and project_key(owner) == project_key(project)
                if (
                    key in desired
                    and own
                    and project_key(path) == project_key(wanted["source"])
                ):
                    continue
                if own and is_link(path):
                    automatic.append(entry)
                else:
                    conflicts.append(entry)
    for key, old in registry["links"].items():
        if project_key(old["project"]) != project_key(project):
            path = root / key
            kind = key.split("_packs/")[0]
            wanted = next(
                (
                    e
                    for k, e in desired.items()
                    if k.startswith(kind + "_packs/") and e["uuid"] == old["uuid"]
                ),
                None,
            )
            if (
                wanted
                and key not in entries
                and os.path.lexists(path)
                and is_link(path)
                and not path.is_dir()
                and project_key(path) == project_key(old["source"])
            ):
                durable = ownership["links"].get(key)
                if durable and durable["entry"] != old:
                    issues.append(
                        {
                            "code": "ownership_changed",
                            "path": str(path),
                            "message": "悬空链接与持久归属不一致",
                        }
                    )
                    continue
                entry = {
                    "key": key,
                    "kind": kind,
                    "uuid": old["uuid"],
                    "path": str(path),
                    "target": str(path.resolve()),
                    "project": old["project"],
                    "is_link": True,
                    "manifest_digest": old.get("manifest_digest"),
                    "evidence": {"type": "ownership", "owner_id": durable["owner_id"]}
                    if durable
                    else {"type": "registry", "entry": old},
                }
                entries[key] = entry
                conflicts.append(dict(entry, source=wanted["source"]))
            continue
        if key not in entries:
            path = root / key
            if (
                os.path.lexists(path)
                and is_link(path)
                and project_key(path) == project_key(old["source"])
                and key not in desired
            ):
                entries[key] = {
                    "key": key,
                    "kind": key.split("_packs/")[0],
                    "uuid": old["uuid"],
                    "project": project,
                    "path": str(path),
                    "target": old["source"],
                    "is_link": True,
                    "evidence": {"type": "registry", "entry": old},
                }
            elif os.path.lexists(path) or not Path(old["source"]).is_dir():
                issues.append(
                    {
                        "code": "link_modified",
                        "path": str(path),
                        "message": "链接或来源缺失，不能保证可恢复",
                    }
                )
            elif key in desired:
                automatic.append(
                    {
                        "key": key,
                        "kind": key.split("_packs/")[0],
                        "uuid": old["uuid"],
                        "project": project,
                        "path": str(path),
                        "target": old["source"],
                        "missing": True,
                    }
                )
    relevant = [project] + [
        e["project"] for e in conflicts + automatic if e.get("project")
    ]
    blockers = process_blockers(root, relevant, exclude, known_projects=all_projects)
    # Bind ownership changes, not generated code or the new session ID.
    snapshot = {
        "root": str(root),
        "project": project,
        "desired": {
            k: {x: e.get(x) for x in ("source", "uuid", "manifest_digest")}
            for k, e in desired.items()
        },
        "entries": entries,
        "registry": registry,
        "ownership": ownership,
        "receipt": receipt,
        "from_project": str(Path(from_project).resolve()) if from_project else None,
        "receipt_raw": receipt_raw,
        "related_receipts": {
            project_key(p): record(owner_path(p))
            for p in relevant
            if project_key(p) != project_key(project)
        },
    }
    return {
        "project": project,
        "global_root": str(root),
        "desired": desired,
        "conflicts": conflicts,
        "automatic": automatic,
        "issues": issues,
        "blockers": blockers,
        "entries": entries,
        "plan_digest": digest(snapshot),
        "registry": registry,
        "ownership": ownership,
        "receipt": receipt,
        "receipt_raw": receipt_raw,
    }


def require_unblocked(plan):
    if plan["issues"]:
        raise EngineError(
            "部署归属需要核对，未修改现场。",
            plan["issues"][0]["code"],
            "使用 deployment inspect 查看完整证据。",
            issues=plan["issues"],
        )
    if plan["blockers"]:
        unknown = any(b["state"] == "unknown" for b in plan["blockers"])
        raise EngineError(
            "无法确认部署空闲。" if unknown else "相关部署仍被会话使用。",
            "occupancy_unknown" if unknown else "deployment_in_use",
            "保存退出相关游戏后重新预览；不会自动终止游戏。",
            blockers=plan["blockers"],
        )


def receipt_recovery(plan, action, from_project=None):
    """Only explicit operations can replace a lost or copied local identity."""
    receipt = plan["receipt"]
    expected = plan["ownership"]["owners"].get(project_key(plan["project"]))
    if (
        action == "repair"
        and expected
        and expected.get("id")
        and project_key(expected.get("project", "")) == project_key(plan["project"])
    ) and (
        not receipt
        or project_key(receipt.get("project", "")) == project_key(plan["project"])
    ):
        return expected
    if (
        action == "migrate"
        and receipt
        and from_project
        and project_key(receipt.get("project", "")) == project_key(from_project)
    ):
        previous = plan["ownership"]["owners"].get(project_key(from_project)) or record(
            owner_path(from_project)
        )
        if previous and receipt.get("id") == previous.get("id"):
            return {"relocated": True}
    return None


def permitted_receipt_issues(plan, action, from_project=None):
    if not receipt_recovery(plan, action, from_project):
        return plan["issues"]
    return [
        e for e in plan["issues"] if e.get("path") != str(owner_path(plan["project"]))
    ]
