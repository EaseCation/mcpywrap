"""Owned global links. Changes are journaled; real directories are never removed."""

import os
from pathlib import Path

from ..engines.host import EngineError
from ..runtime import occupancy, storage
from ..utils.locks import directory_lock
from ..utils.paths import is_link
from .symlinks import _create_directory_link


def unlink(path):
    if not is_link(path):
        raise EngineError("拒绝删除不是链接的目录：" + str(path), "link_modified")
    if Path(path).is_symlink():
        Path(path).unlink()
    else:
        os.rmdir(path)


def pack_uuid(path):
    for filename in ("manifest.json", "pack_manifest.json"):
        file = Path(path) / filename
        if file.is_file():
            import json
            import uuid

            try:
                return str(
                    uuid.UUID(
                        json.loads(file.read_text(encoding="utf-8-sig"))["header"][
                            "uuid"
                        ]
                    )
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise EngineError(
                    "无效的运行包 manifest：" + str(file), "invalid_manifest"
                ) from exc
    return None


class ManagedLinks:
    def __init__(self, root, project):
        self.root = Path(root).resolve()
        self.project = str(Path(project).resolve())
        self.store = self.root / ".mcpywrap"
        self.path = self.store / "links.json"
        self.ownership_path = self.store / "ownership.json"
        self.journal_path = (
            self.store / "links.transaction.json"
        )  # Legacy recovery only.

    def lock(self):
        for path in (
            self.store,
            self.store / "transactions",
            self.store / "operations",
        ):
            if is_link(path):
                raise EngineError(
                    "全局部署登记目录被替换为链接：" + str(path), "ownership_changed"
                )
        return directory_lock(self.store, reentrant=True)

    def transaction_path(self, transaction):
        return self.store / "transactions" / (storage.identifier(transaction) + ".json")

    def _validate(self, key, entry):
        from ..runtime.deployment_inspection import validate_key

        validate_key(key)
        path = self.root / key
        if not is_link(path) or occupancy.path_key(path) != occupancy.path_key(
            entry["source"]
        ):
            raise EngineError(
                "全局包链接已被外部修改：" + str(path),
                "link_modified",
                "请检查链接目标，未覆盖未知内容。",
                conflict=str(path),
            )

    def _legacy(self, kind, path):
        from ..runtime.deployment_inspection import legacy_evidence

        return bool(legacy_evidence(self.project, kind, path))

    def _pending(self, identities, transaction=None):
        from ..runtime.deployment_inspection import record

        for path in sorted((self.store / "transactions").glob("*.json")):
            value = record(path)
            if not value or value["id"] == transaction:
                continue
            if identities.intersection(value.get("identities", [])):
                alive = occupancy.live(
                    {"worker": value.get("owner"), "game": value.get("game")}
                )
                raise EngineError(
                    "相关包有未提交的部署事务。",
                    "busy" if alive else "recovery_required",
                    "使用旧项目的 deployment repair 预览恢复。",
                    operation_id=value["id"],
                    project=value["project"],
                )

    def publish(
        self, packs, deployment, session=None, transaction=None, migration=None
    ):
        from ..runtime.deployment_inspection import desired_packs

        desired = desired_packs(self.project, packs, deployment)
        from ..runtime.deployment_service import operation_locks, operation_projects

        with operation_locks(
            self.root,
            operation_projects(self.root, self.project, (migration or {}).get("from")),
        ):
            return self._publish(desired, session, transaction, migration)

    def _publish(
        self,
        desired,
        session=None,
        transaction=None,
        migration=None,
        retiring=(),
        explicit=False,
        repair_receipt=False,
        plan_digest=None,
    ):
        import uuid

        from ..runtime.deployment_inspection import (
            inspect,
            migration_origin,
            owner_path,
            permitted_receipt_issues,
            process_blockers,
            project_key,
            receipt_recovery,
            require_unblocked,
        )

        transaction_id = transaction or uuid.uuid4().hex
        with self.lock():
            self.recover()
            identities = {k.split("/")[0] + "/" + e["uuid"] for k, e in desired.items()}
            plan = inspect(
                self.root,
                self.project,
                desired,
                (migration or {}).get("from"),
                exclude=(session,) if session else (),
            )
            for key in retiring:
                if key in plan["entries"]:
                    e = plan["entries"][key]
                    identities.add(e["kind"] + "_packs/" + e["uuid"])
            identities.update(
                k.split("/")[0] + "/" + e["uuid"]
                for k, e in plan["registry"]["links"].items()
                if project_key(e["project"]) == project_key(self.project)
            )
            self._pending(identities, transaction_id)
            if migration and migration.get("expect") != plan["plan_digest"]:
                raise EngineError(
                    "部署现场已变化，请重新预览。",
                    "plan_stale",
                    plan_digest=plan["plan_digest"],
                )
            authorization = (
                "migrate" if migration else "repair" if repair_receipt else "publish"
            )
            effective_issues = permitted_receipt_issues(
                plan, authorization, (migration or {}).get("from")
            )
            checked = dict(plan, issues=effective_issues)
            if effective_issues:
                require_unblocked(checked)
            registry, ownership = plan["registry"], plan["ownership"]
            old = registry["links"]
            wanted_ids = {k.split("/")[0] + "/" + e["uuid"] for k, e in desired.items()}
            for relation in ownership["migrations"]:
                if project_key(relation["from"]) == project_key(
                    self.project
                ) and wanted_ids.intersection(relation["identities"]):
                    raise EngineError(
                        "此项目的包已迁移到：" + relation["to"],
                        "deployment_relocated",
                        "请从新项目入口运行；不会自动抢回已迁移包。",
                        project=relation["to"],
                    )
            remove = {
                key: value
                for key, value in old.items()
                if project_key(value["project"]) == project_key(self.project)
                and key not in desired
            }
            # Explicit retire never expands to unselected links.
            if retiring:
                remove = {}
                for key in retiring:
                    e = plan["entries"].get(key)
                    if not e or not e["is_link"] or not Path(e["target"]).is_dir():
                        raise EngineError(
                            "退役对象不是可恢复的目录链接。",
                            "link_modified",
                            path=str(self.root / key),
                        )
                    if not explicit and (
                        not e["project"]
                        or project_key(e["project"]) != project_key(self.project)
                    ):
                        raise EngineError("退役链接归属不明。", "ownership_changed")
                    remove[key] = old.get(key) or {
                        "project": e["project"] or self.project,
                        "source": e["target"],
                        "uuid": e["uuid"],
                        "deployment": None,
                    }
            for e in plan["automatic"]:
                if not e.get("missing"):
                    remove[e["key"]] = old.get(e["key"]) or {
                        "project": self.project,
                        "source": e["target"],
                        "uuid": e["uuid"],
                        "deployment": None,
                    }
            relations = []
            unhandled = []
            for e in plan["conflicts"]:
                identity = e["kind"] + "_packs/" + e["uuid"]
                authorized = bool(
                    migration
                    and e["project"]
                    and project_key(e["project"]) == project_key(migration["from"])
                )
                authorized = authorized or any(
                    project_key(r["to"]) == project_key(self.project)
                    and e["project"]
                    and project_key(r["from"]) == project_key(e["project"])
                    and identity in r["identities"]
                    and r.get("origins", {}).get(identity) is not None
                    and r["origins"][identity] == migration_origin(plan, e)
                    for r in ownership["migrations"]
                )
                if not authorized or not e["is_link"] or not e["evidence"]:
                    unhandled.append(e)
                    continue
                remove[e["key"]] = old.get(e["key"]) or {
                    "project": e["project"],
                    "source": e["target"],
                    "uuid": e["uuid"],
                    "deployment": None,
                }
            if unhandled:
                from ..runtime.deployment_service import recovery_actions

                actions = recovery_actions(plan, session)
                raise EngineError(
                    "全局包 UUID 冲突："
                    + ", ".join(sorted({e["uuid"] for e in unhandled})),
                    "pack_conflict",
                    "请查看冲突双方路径，并预览迁移或退役操作。",
                    conflicts=plan["conflicts"],
                    actions=actions,
                    source=unhandled[0]["source"],
                    conflict=unhandled[0]["path"],
                )
            if migration:
                selected = [e for e in plan["conflicts"] if e["key"] in remove]
                if selected:
                    relations = [
                        {
                            "id": transaction_id,
                            "from": str(Path(migration["from"]).resolve()),
                            "to": self.project,
                            "identities": sorted(
                                {e["kind"] + "_packs/" + e["uuid"] for e in selected}
                            ),
                            "origins": {
                                e["kind"] + "_packs/" + e["uuid"]: migration_origin(
                                    plan, e
                                )
                                for e in selected
                            },
                        }
                    ]
            changes = []
            for key, entry in remove.items():
                exists = os.path.lexists(self.root / key)
                if exists:
                    self._validate(key, entry)
                elif not Path(entry["source"]).is_dir():
                    raise EngineError(
                        "旧链接来源缺失，无法保证回滚。", "recovery_required"
                    )
                from ..utils.link_snapshot import capture

                changes.append(
                    {
                        "key": key,
                        "old": entry,
                        "new": None,
                        "old_exists": exists,
                        "link_state": capture(self.root / key) if exists else None,
                    }
                )
            for key, entry in desired.items():
                path = self.root / key
                exists = os.path.lexists(path)
                if exists and key not in old:
                    evidence = plan["entries"].get(key)
                    if not (
                        evidence
                        and evidence["project"]
                        and evidence["evidence"]
                        and project_key(evidence["project"])
                        == project_key(self.project)
                        and evidence["is_link"]
                        and project_key(evidence["target"])
                        == project_key(entry["source"])
                    ):
                        raise EngineError(
                            "运行链接名称被未登记内容占用：" + str(path),
                            "link_conflict",
                        )
                if exists and key in old:
                    self._validate(key, old[key])
                if not exists or (
                    key in old
                    and project_key(old[key]["source"]) != project_key(entry["source"])
                ):
                    from ..utils.link_snapshot import capture

                    changes.append(
                        {
                            "key": key,
                            "old": old.get(key),
                            "new": entry,
                            "old_exists": exists,
                            "link_state": capture(path) if exists else None,
                        }
                    )
            if retiring:
                affected = [self.project] + [
                    e["project"]
                    for key, e in plan["entries"].items()
                    if key in retiring and e.get("project")
                ]
                checked["blockers"] = process_blockers(
                    self.root,
                    affected,
                    exclude=(session,) if session else (),
                    known_projects=[e["project"] for e in old.values()],
                )
            if any(c["old"] for c in changes) or migration or retiring:
                require_unblocked(checked)
            receipt_path = owner_path(self.project)
            before_receipt = plan["receipt"]
            recovered = receipt_recovery(
                plan, authorization, (migration or {}).get("from")
            )
            receipt = (
                recovered
                if recovered and not recovered.get("relocated")
                else before_receipt
                if before_receipt and not (recovered or {}).get("relocated")
                else {
                    "schema_version": 1,
                    "id": uuid.uuid4().hex,
                    "project": self.project,
                }
            )
            owner_updates = {project_key(self.project): receipt}
            link_updates = {key: None for key in remove}
            link_updates.update(
                {
                    key: {
                        "owner_id": receipt["id"],
                        "entry": entry,
                        "evidence": (ownership["links"].get(key) or {}).get("evidence")
                        or (plan["entries"].get(key) or {}).get("evidence")
                        or {"type": "publication", "session": session},
                    }
                    for key, entry in desired.items()
                }
            )
            ledger_changes = []
            for section, updates in (
                ("owners", owner_updates),
                ("links", link_updates),
            ):
                for key, value in updates.items():
                    if ownership[section].get(key) != value:
                        ledger_changes.append(
                            {
                                "section": section,
                                "key": key,
                                "old": ownership[section].get(key),
                                "new": value,
                            }
                        )
            from .processes import identity

            journal = {
                "id": transaction_id,
                "project": self.project,
                "previous": registry,
                "changes": changes,
                "applied": [],
                "registry_keys": sorted(set(remove) | set(desired)),
                "published": desired,
                "owner": identity(os.getpid()),
                "identities": sorted(identities),
                "ledger_changes": ledger_changes,
                "relations": relations,
                "receipt": {
                    "path": str(receipt_path),
                    "old": before_receipt,
                    "new": receipt,
                    "old_raw": plan.get("receipt_raw"),
                },
                "state": "applying",
                "session": session,
                "plan_digest": plan_digest or (migration or {}).get("plan_digest"),
            }
            if session:
                journal["session_path"] = str(
                    Path(self.project) / ".runtime/sessions" / session / "session.json"
                )
            path = self.transaction_path(transaction_id)
            storage.write(path, journal)
            try:
                for change in changes:
                    journal["applied"].append(change)
                    storage.write(path, journal)
                    target = self.root / change["key"]
                    if change["old_exists"]:
                        self._validate(change["key"], change["old"])
                        unlink(target)
                    if change["new"]:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        _create_directory_link(change["new"]["source"], str(target))
                links = dict(old)
                for key in remove:
                    links.pop(key, None)
                links.update(desired)
                storage.write(self.path, {"schema_version": 1, "links": links})
                for change in ledger_changes:
                    section = ownership[change["section"]]
                    if change["new"] is None:
                        section.pop(change["key"], None)
                    else:
                        section[change["key"]] = change["new"]
                ownership["migrations"].extend(relations)
                storage.write(self.ownership_path, ownership)
                storage.write(receipt_path, receipt)
                journal["state"] = "published"
                storage.write(path, journal)
                result = {
                    kind: [
                        Path(k).name for k in desired if k.startswith(kind + "_packs/")
                    ]
                    for kind in ("behavior", "resource")
                }
                if transaction is None:
                    self.commit(transaction_id)
                return result, journal
            except BaseException:
                self.restore(journal)
                raise

    def recover(self):
        # Older releases used a single short-lived journal. New reservations are
        # per operation and are recovered by the owning deployment coordinator.
        from ..runtime.deployment_inspection import record

        journal = record(self.journal_path)
        if journal:
            if occupancy.live({"worker": journal["owner"]}):
                raise EngineError("另一个操作正在修改全局包链接。", "busy")
            self.restore(journal)

    def finish(self, transaction):
        # Publication is not a commit: retain the UUID reservation until ready.
        return None

    def update(self, transaction, **values):
        with self.lock():
            path = self.transaction_path(transaction)
            journal = storage.read(path)
            if journal:
                journal.update(values)
                storage.write(path, journal)

    def commit(self, transaction):
        with self.lock():
            path = self.transaction_path(transaction)
            journal = storage.read(path)
            if journal:
                journal["state"] = "committed"
                storage.write(
                    self.store / "operations" / (transaction + ".json"), journal
                )
                path.unlink(missing_ok=True)

    def validate_restore(self, journal):
        """Read-only recovery validation, also used by previews."""
        from ..runtime.deployment_inspection import record, validate_key

        if occupancy.path_key(
            journal.get("project", self.project)
        ) != occupancy.path_key(self.project):
            raise EngineError("恢复记录不属于当前项目。", "recovery_required")
        for change in journal["changes"] + journal["applied"]:
            validate_key(change["key"])
        if journal.get("receipt"):
            from ..runtime.deployment_inspection import owner_path

            if Path(journal["receipt"]["path"]) != owner_path(self.project):
                raise EngineError("恢复身份路径不属于当前项目。", "recovery_required")
        current = record(self.path, {"schema_version": 1, "links": {}})
        ownership = record(
            self.ownership_path,
            {"schema_version": 1, "owners": {}, "links": {}, "migrations": []},
        )
        keys = journal.get("registry_keys", [c["key"] for c in journal["changes"]])
        for key in keys:
            validate_key(key)
            entry = current["links"].get(key)
            if "published" in journal and entry not in (
                journal["previous"]["links"].get(key),
                journal["published"].get(key),
            ):
                raise EngineError(
                    "链接归属在启动后发生变化，已保留现场：" + key,
                    "recovery_required",
                )
        for change in journal.get("ledger_changes", []):
            if change["section"] not in ("owners", "links"):
                raise EngineError("恢复归属记录无效。", "recovery_required")
            if ownership[change["section"]].get(change["key"]) not in (
                change["old"],
                change["new"],
            ):
                raise EngineError(
                    "持久归属被外部修改，已保留恢复记录。", "recovery_required"
                )
        receipt = journal.get("receipt")
        if receipt:
            import base64

            raw = (
                Path(receipt["path"]).read_bytes()
                if Path(receipt["path"]).exists()
                else None
            )
            original = (
                base64.b64decode(receipt["old_raw"]) if receipt.get("old_raw") else None
            )
            if not (original is not None and raw == original) and record(
                receipt["path"]
            ) not in (receipt["old"], receipt["new"]):
                raise EngineError("项目部署身份被外部修改。", "recovery_required")
        # Validate *all* paths before the first rollback mutation.
        for change in journal["applied"]:
            path = self.root / change["key"]
            if change.get("link_state"):
                from ..utils.link_snapshot import validate

                try:
                    target = validate(path, change["link_state"])
                    if change.get("old") and occupancy.path_key(
                        target
                    ) != occupancy.path_key(change["old"]["source"]):
                        raise ValueError("链接快照与原目标不符")
                except (ValueError, KeyError, UnicodeError) as error:
                    raise EngineError(
                        "恢复链接快照无效。", "recovery_required"
                    ) from error
            if os.path.lexists(path):
                expected = [
                    occupancy.path_key(e["source"])
                    for e in (change["old"], change["new"])
                    if e
                ]
                if not is_link(path) or occupancy.path_key(path) not in expected:
                    raise EngineError(
                        "恢复时链接已被外部修改：" + str(path), "recovery_required"
                    )
            if (
                change["old"]
                and change.get("old_exists", True)
                and not change.get("link_state")
                and not Path(change["old"]["source"]).is_dir()
            ):
                raise EngineError(
                    "恢复来源已缺失，已保留恢复记录。", "recovery_required"
                )
        return current, ownership, keys, receipt

    def restore(self, journal):
        from ..runtime.deployment_inspection import record

        with self.lock():
            current, ownership, keys, receipt = self.validate_restore(journal)
            for change in reversed(journal["applied"]):
                path = self.root / change["key"]
                restored = False
                if os.path.lexists(path):
                    if (
                        change["old"]
                        and change.get("old_exists", True)
                        and occupancy.path_key(path)
                        == occupancy.path_key(change["old"]["source"])
                    ):
                        restored = True
                    else:
                        unlink(path)
                if change["old"] and change.get("old_exists", True) and not restored:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if change.get("link_state"):
                        from ..utils.link_snapshot import restore

                        restore(path, change["link_state"])
                    else:
                        _create_directory_link(change["old"]["source"], str(path))
            for key in keys:
                prior = journal["previous"]["links"].get(key)
                if prior is None:
                    current["links"].pop(key, None)
                else:
                    current["links"][key] = prior
            storage.write(self.path, current)
            for change in journal.get("ledger_changes", []):
                section = ownership[change["section"]]
                if change["old"] is None:
                    section.pop(change["key"], None)
                else:
                    section[change["key"]] = change["old"]
            relations = {r["id"] for r in journal.get("relations", [])}
            ownership["migrations"] = [
                r for r in ownership["migrations"] if r["id"] not in relations
            ]
            if journal.get("ledger_changes") or journal.get("relations"):
                storage.write(self.ownership_path, ownership)
            if receipt:
                if receipt.get("old_raw"):
                    import base64

                    storage.write_bytes(
                        receipt["path"], base64.b64decode(receipt["old_raw"])
                    )
                elif receipt["old"] is None:
                    Path(receipt["path"]).unlink(missing_ok=True)
                else:
                    storage.write(receipt["path"], receipt["old"])
            if journal.get("id"):
                storage.write(
                    self.store / "operations" / (journal["id"] + ".json"),
                    dict(journal, state="rolled_back"),
                )
                self.transaction_path(journal["id"]).unlink(missing_ok=True)
            legacy = record(self.journal_path)
            if legacy and legacy.get("id") == journal.get("id"):
                self.journal_path.unlink(missing_ok=True)
