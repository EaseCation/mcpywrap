"""Historical profiles, real junctions and interrupted ownership transitions."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner
from test_runtime_deployment import directory_link, fixture

from mcpywrap_core.cli import cli
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.mcstudio.deployment_links import ManagedLinks
from mcpywrap_core.runtime import instances, storage
from mcpywrap_core.runtime.deployment import Deployment, inventory
from mcpywrap_core.runtime.deployment_inspection import inspect
from mcpywrap_core.runtime.deployment_service import execute, preview
from mcpywrap_core.utils.link_snapshot import capture, restore, validate


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = fixture(self.root, "main")
        self.engine = self.root / "engine"
        self.manager = ManagedLinks(self.engine, self.project)

    def publish(self, project=None, transaction=None, migration=None):
        project = project or self.project
        deployment = Deployment(project)
        with deployment.lock():
            pack = deployment.prepare()
            deployment.begin_launch()
            deployment.publish_links(self.engine, [pack], migration=migration)
            if transaction is None:
                deployment.commit()
        return deployment, pack

    @unittest.skipUnless(os.name == "nt", "Windows namespace targets")
    def test_symlink_snapshot_namespace_preserves_identity_and_raw_restore_target(self):
        from mcpywrap_core.runtime.occupancy import path_key

        path = self.engine / "behavior_packs/old-link"
        for prefix in ("\\\\?\\", "\\??\\"):
            with self.subTest(prefix=prefix):
                original = prefix + str(self.project)
                state = {"type": "symlink", "target": original}
                self.assertEqual(
                    path_key(validate(path, state)), path_key(self.project)
                )
                self.assertEqual(state["target"], original)
                for unc_prefix in ("UNC\\", "unc\\"):
                    unc = {
                        "type": "symlink",
                        "target": prefix + unc_prefix + "server\\share\\pack",
                    }
                    self.assertEqual(validate(path, unc), "\\\\server\\share\\pack")

    def legacy(self, project=None):
        project = project or self.project
        refs = {}
        for kind in ("behavior", "resource"):
            path = self.engine / (kind + "_packs") / ("old_" + kind)
            path.parent.mkdir(parents=True, exist_ok=True)
            directory_link(project / (kind + "_pack"), path)
            refs[kind + "_packs"] = [path.name]
        storage.write(project / ".runtime/old.cppconfig", {"world_info": refs})

    def split(self):
        self.legacy()
        child = fixture(self.project, "shantou")
        for kind in ("behavior", "resource"):
            shutil.copyfile(
                self.project / (kind + "_pack/manifest.json"),
                child / (kind + "_pack/manifest.json"),
            )
        sid = "a" * 32
        storage.write(
            child / ".runtime/sessions" / sid / "session.json",
            {
                "project": str(child),
                "session": sid,
                "state": "failed",
                "mode": "local",
                "backend": "windows",
                "game": None,
                "worker": None,
                "level_id": "world",
                "engine_overrides": {},
                "created_at": 1,
                "config_path": str(child / ".runtime/world.cppconfig"),
            },
        )
        return child, sid

    def historical_failure(self):
        child, sid = self.split()
        path = child / ".runtime/sessions" / sid / "session.json"
        data = storage.read(path)
        data.update(code="pack_conflict", error="全局包 UUID 冲突：旧记录没有 actions")
        storage.write(path, data)
        storage.write(
            instances.record_path(child, "world"),
            {
                "level_id": "world",
                "name": "legacy",
                "state": "failed",
                "last_session": sid,
                "created_at": 1,
            },
        )
        return child, sid

    def test_normal_run_restores_guidance_before_instance_selection_blocks(self):
        child, sid = self.historical_failure()
        before = (child / ".runtime/sessions" / sid / "session.json").read_bytes()
        runner = CliRunner()
        base = [
            "--local",
            "--project",
            str(child),
            "--non-interactive",
            "run",
            "--no-gui",
            "--detach",
        ]
        with (
            patch(
                "mcpywrap_core.runtime.deployment_service.global_root",
                return_value=self.engine,
            ),
            patch(
                "mcpywrap_core.engines.backend.describe", return_value={"backend": "windows"}
            ),
            patch(
                "mcpywrap_core.runtime.windows.discover_engines",
                side_effect=AssertionError("must not launch"),
            ),
        ):
            result = runner.invoke(cli, base + ["--json"])
            value = json.loads(result.stdout)
            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(value["code"], "pack_conflict")
            self.assertEqual(len(value["details"]["conflicts"]), 2)
            action = next(a for a in value["actions"] if a.get("kind") == "migrate")
            self.assertEqual(action["argv"][-2:], ["--session", sid])
            human = runner.invoke(cli, base)
            self.assertIn("只读预览", human.output)
            self.assertIn("migrate", human.output)
            self.assertIn(sid, human.output)
        self.assertEqual(
            (child / ".runtime/sessions" / sid / "session.json").read_bytes(), before
        )
        self.assertEqual(len(list((child / ".runtime/sessions").iterdir())), 1)
        self.assertFalse((child / ".mcpy/runtime/assembled").exists())

    def test_resolved_historical_conflict_is_not_presented_as_current(self):
        from mcpywrap_core.mcstudio.deployment_links import unlink
        from mcpywrap_core.runtime.deployment_service import startup_problem

        child, _sid = self.historical_failure()
        for kind in ("behavior", "resource"):
            unlink(self.engine / (kind + "_packs") / ("old_" + kind))
        with patch(
            "mcpywrap_core.runtime.deployment_service.global_root", return_value=self.engine
        ):
            self.assertIsNone(startup_problem(child))

    def test_missing_history_keeps_explicit_world_retry_guidance(self):
        child, sid = self.historical_failure()
        (child / ".runtime/sessions" / sid / "session.json").unlink()
        with patch(
            "mcpywrap_core.engines.backend.describe", return_value={"backend": "windows"}
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "--local",
                    "--project",
                    str(child),
                    "--non-interactive",
                    "run",
                    "--no-gui",
                    "--detach",
                    "--json",
                ],
            )
        value = json.loads(result.stdout)
        self.assertEqual(value["code"], "instance_not_ready")
        self.assertIn("run world", value["hint"])

    def test_initialized_world_with_failed_last_launch_still_has_guidance(self):
        from mcpywrap_core.runtime.deployment_service import startup_problem

        child, sid = self.historical_failure()
        meta = storage.read(instances.record_path(child, "world"))
        meta["last_ready_at"] = 1
        storage.write(instances.record_path(child, "world"), meta)
        self.assertEqual(instances.list_instances(child)[0]["state"], "ready")
        with patch(
            "mcpywrap_core.runtime.deployment_service.global_root", return_value=self.engine
        ):
            value = startup_problem(child)
        self.assertEqual(value["code"], "pack_conflict")
        self.assertEqual(value["session"], sid)

    def test_inspection_reports_both_conflicts_without_writing(self):
        child, sid = self.split()
        before = sorted(str(p) for p in self.root.rglob("*"))
        value = preview(child, "migrate", self.project, sid, root=self.engine)
        self.assertEqual(len(value["conflicts"]), 2)
        self.assertEqual(len(value["changes"]), 2)
        self.assertTrue(value["can_apply"])
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), before)
        self.assertIn("--expect", value["apply_argv"])

    def test_parent_without_project_configuration_remains_identifiable(self):
        child, sid = self.split()
        (self.project / "pyproject.toml").unlink()
        value = preview(child, "migrate", self.project, sid, root=self.engine)
        self.assertTrue(value["can_apply"])
        self.assertTrue(
            all(e["project"] == str(self.project) for e in value["conflicts"])
        )

    def test_session_cppconfig_survives_loss_of_top_level_recipe(self):
        self.legacy()
        source = self.project / ".runtime/old.cppconfig"
        dest = self.project / ".runtime/sessions" / ("b" * 32) / "runtime.cppconfig"
        dest.parent.mkdir(parents=True)
        source.rename(dest)
        self.publish()
        self.assertFalse(os.path.lexists(self.engine / "behavior_packs/old_behavior"))

    def test_delete_only_instance_preserves_registration_and_rerun(self):
        self.legacy()
        with (
            patch(
                "mcpywrap_core.runtime.deployment_service.global_root",
                return_value=self.engine,
            ),
            patch.object(instances, "world_path", return_value=self.root / "world"),
        ):
            instances.delete(
                self.project,
                [
                    {
                        "level_id": "old",
                        "config_path": str(self.project / ".runtime/old.cppconfig"),
                    }
                ],
            )
        self.assertTrue((self.project / ".runtime/deployment-owner.json").is_file())
        self.assertFalse((self.project / ".runtime/old.cppconfig").exists())
        self.publish()
        self.assertFalse(os.path.lexists(self.engine / "behavior_packs/old_behavior"))

    def test_migration_commit_prevents_old_project_reclaim(self):
        child, sid = self.split()
        plan = preview(child, "migrate", self.project, sid, root=self.engine)
        self.publish(
            child,
            migration={
                "from": str(self.project),
                "expect": plan["inspection_digest"],
                "plan_digest": plan["plan_digest"],
            },
        )
        self.assertFalse(os.path.lexists(self.engine / "behavior_packs/old_behavior"))
        with self.assertRaises(EngineError) as error:
            self.publish()
        self.assertEqual(error.exception.code, "deployment_relocated")
        self.assertEqual(
            len(storage.read(self.manager.ownership_path)["migrations"]), 1
        )
        value = execute(
            child,
            "migrate",
            self.project,
            sid,
            expect=plan["plan_digest"],
            root=self.engine,
        )
        self.assertEqual(value["state"], "already_applied")

    def test_migration_rollback_restores_links_receipts_and_relation(self):
        child, sid = self.split()
        old = {
            k: (self.engine / (k + "_packs") / ("old_" + k)).resolve()
            for k in ("behavior", "resource")
        }
        plan = preview(child, "migrate", self.project, sid, root=self.engine)
        dep, _ = self.publish(
            child,
            transaction="pending",
            migration={"from": str(self.project), "expect": plan["inspection_digest"]},
        )
        with dep.lock():
            dep.rollback()
        for kind, target in old.items():
            self.assertEqual(
                (self.engine / (kind + "_packs") / ("old_" + kind)).resolve(), target
            )
        self.assertFalse((child / ".runtime/deployment-owner.json").exists())
        self.assertEqual(storage.read(self.manager.ownership_path)["migrations"], [])
        self.assertEqual(list((self.manager.store / "transactions").glob("*.json")), [])

    def test_confirmed_origin_is_reused_without_expanding_authorization(self):
        child, sid = self.split()
        plan = preview(child, "migrate", self.project, sid, root=self.engine)
        self.publish(
            child,
            migration={"from": str(self.project), "expect": plan["inspection_digest"]},
        )
        self.legacy()
        self.publish(child)
        self.assertFalse(os.path.lexists(self.engine / "behavior_packs/old_behavior"))
        self.legacy()
        storage.write(
            self.project / ".runtime/deployment-owner.json",
            {"schema_version": 1, "id": "f" * 32, "project": str(self.project)},
        )
        with self.assertRaises(EngineError) as error:
            self.publish(child)
        self.assertEqual(error.exception.code, "pack_conflict")

    def test_map_preview_uses_exact_runtime_layout_and_installed_dependencies(self):
        from mcpywrap_core.dependencies import write_project
        from mcpywrap_core.runtime.deployment_inspection import desired_packs, project_packs

        source = fixture(self.root, "map-source")
        world = self.root / "map"
        world.mkdir()
        shutil.copytree(source / "behavior_pack", world / "behavior_packs/main")
        write_project(
            world,
            {
                "project": {"name": "map"},
                "tool": {
                    "mcpywrap": {
                        "project_type": "map",
                        "local_dependencies": ["../main"],
                    }
                },
            },
        )
        before = sorted(str(p) for p in self.root.rglob("*"))
        inspected = project_packs(world)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob("*")))
        deployment = Deployment(world)
        with deployment.lock():
            packs = deployment.prepare()
            actual = desired_packs(world, packs)
            self.assertEqual(inspected, actual)
            deployment.rollback()

    def test_second_link_failure_restores_first_and_metadata(self):
        child, sid = self.split()
        plan = preview(child, "migrate", self.project, sid, root=self.engine)
        from mcpywrap_core.mcstudio.symlinks import _create_directory_link

        def fail(source, target):
            if "resource_packs" in str(target):
                raise OSError("injected resource publication failure")
            return _create_directory_link(source, target)

        with (
            patch(
                "mcpywrap_core.mcstudio.deployment_links._create_directory_link",
                side_effect=fail,
            ),
            self.assertRaisesRegex(OSError, "injected"),
        ):
            self.publish(
                child,
                migration={
                    "from": str(self.project),
                    "expect": plan["inspection_digest"],
                },
            )
        self.assertTrue((self.engine / "behavior_packs/old_behavior").is_dir())
        self.assertTrue((self.engine / "resource_packs/old_resource").is_dir())

    def test_plan_stale_after_link_target_change(self):
        child, sid = self.split()
        plan = preview(child, "migrate", self.project, sid, root=self.engine)
        storage.write(
            self.project / ".runtime/extra.cppconfig",
            {"world_info": {"name": "changed"}},
        )
        # Evidence digest changes when the actual referencing recipe changes.
        storage.write(
            self.project / ".runtime/old.cppconfig",
            {
                "world_info": {
                    "behavior_packs": ["old_behavior"],
                    "resource_packs": ["old_resource"],
                    "name": "changed",
                }
            },
        )
        with self.assertRaises(EngineError) as error:
            execute(
                child,
                "migrate",
                self.project,
                sid,
                expect=plan["plan_digest"],
                root=self.engine,
            )
        self.assertEqual(error.exception.code, "plan_stale")

    def test_copied_owner_receipt_does_not_authorize_another_path(self):
        self.publish()
        other = fixture(self.root, "copy")
        (other / ".runtime").mkdir()
        shutil.copyfile(
            self.project / ".runtime/deployment-owner.json",
            other / ".runtime/deployment-owner.json",
        )
        plan = inspect(self.engine, other)
        self.assertEqual(plan["issues"][0]["code"], "ownership_changed")

    def test_missing_receipt_does_not_silently_reclaim_ownership(self):
        self.publish()
        (self.project / ".runtime/deployment-owner.json").unlink()
        with self.assertRaises(EngineError) as error:
            self.publish()
        self.assertEqual(error.exception.code, "ownership_changed")

    def test_missing_and_corrupt_receipt_can_be_explicitly_rebuilt(self):
        self.publish()
        path = self.project / ".runtime/deployment-owner.json"
        original = storage.read(path)
        for content in (None, b"{interrupted identity"):
            if content is None:
                path.unlink()
            else:
                path.write_bytes(content)
            plan = preview(self.project, "repair", root=self.engine)
            self.assertTrue(plan["can_apply"], plan)
            execute(
                self.project, "repair", expect=plan["plan_digest"], root=self.engine
            )
            self.assertEqual(storage.read(path), original)

    def test_dead_publication_is_recovered_by_owning_deployment(self):
        dep, _ = self.publish(transaction="pending")
        dead = {"pid": 99999999, "created_at": 0, "executable": "missing.exe"}
        journal = storage.read(dep.journal_path)
        journal["owner"] = dead
        storage.write(dep.journal_path, journal)
        path = self.manager.transaction_path(journal["id"])
        journal = storage.read(path)
        journal["owner"] = dead
        storage.write(path, journal)
        plan = preview(self.project, "repair", root=self.engine)
        execute(self.project, "repair", expect=plan["plan_digest"], root=self.engine)
        self.assertFalse(dep.journal_path.exists())
        self.assertFalse(path.exists())
        self.assertEqual(storage.read(self.manager.path)["links"], {})

    def test_global_metadata_write_failure_restores_old_links(self):
        child, sid = self.split()
        plan = preview(child, "migrate", self.project, sid, root=self.engine)
        write = storage.write
        failed = []

        def inject(path, value):
            if Path(path) == self.manager.ownership_path and not failed:
                failed.append(True)
                raise OSError("injected ownership write failure")
            return write(path, value)

        with (
            patch.object(storage, "write", side_effect=inject),
            self.assertRaisesRegex(OSError, "injected ownership"),
        ):
            self.publish(
                child,
                migration={
                    "from": str(self.project),
                    "expect": plan["inspection_digest"],
                },
            )
        self.assertTrue((self.engine / "behavior_packs/old_behavior").is_dir())
        self.assertTrue((self.engine / "resource_packs/old_resource").is_dir())

    def test_other_profile_game_is_not_a_blocker(self):
        child, sid = self.split()
        process = Mock(pid=9999, info={"pid": 9999, "name": "Minecraft.Windows.exe"})
        process.environ.return_value = {
            "APPDATA": str(self.root / "other-profile/AppData/Roaming"),
            "USERPROFILE": str(self.root / "other-profile"),
        }
        with patch("psutil.process_iter", return_value=[process]):
            value = preview(child, "migrate", self.project, sid, root=self.engine)
        self.assertTrue(value["can_apply"])

    def test_unverified_appdata_override_remains_unknown(self):
        child, sid = self.split()
        process = Mock(pid=9999, info={"pid": 9999, "name": "Minecraft.Windows.exe"})
        process.environ.return_value = {"APPDATA": str(self.root / "unverified")}
        with patch("psutil.process_iter", return_value=[process]):
            value = preview(child, "migrate", self.project, sid, root=self.engine)
        self.assertFalse(value["can_apply"])
        self.assertEqual(value["blockers"][0]["state"], "unknown")

    def test_missing_owned_link_is_rebuilt_without_changing_source(self):
        self.publish()
        links = storage.read(self.manager.path)["links"]
        from mcpywrap_core.mcstudio.deployment_links import unlink

        key = next(iter(links))
        unlink(self.engine / key)
        before = inventory(self.project / ".mcpy/runtime/assembled")
        plan = preview(self.project, "repair", root=self.engine)
        execute(self.project, "repair", expect=plan["plan_digest"], root=self.engine)
        self.assertTrue((self.engine / key).is_dir())
        self.assertEqual(inventory(self.project / ".mcpy/runtime/assembled"), before)

    def test_repair_adopts_legacy_links_without_building(self):
        self.legacy()
        plan = preview(self.project, "repair", root=self.engine)
        result = execute(
            self.project, "repair", expect=plan["plan_digest"], root=self.engine
        )
        self.assertEqual(result["state"], "completed")
        self.assertIn(
            "behavior_packs/old_behavior", storage.read(self.manager.path)["links"]
        )
        self.assertFalse((self.project / ".mcpy/runtime/assembled").exists())

    def test_retire_preserves_sources_world_and_unrelated_links(self):
        self.publish()
        other = fixture(self.root, "other")
        self.publish(other)
        (self.project / "world-marker").write_bytes(b"world")
        plan = preview(self.project, "retire", root=self.engine)
        execute(self.project, "retire", expect=plan["plan_digest"], root=self.engine)
        self.assertEqual((self.project / "world-marker").read_bytes(), b"world")
        self.assertTrue(
            (
                self.project / ".mcpy/runtime/assembled/behavior_pack/manifest.json"
            ).exists()
        )
        self.assertEqual(len(storage.read(self.manager.path)["links"]), 2)

    def test_explicit_retire_of_unknown_link_does_not_require_false_ownership(self):
        folder = self.engine / "behavior_packs"
        folder.mkdir(parents=True)
        directory_link(self.project / "behavior_pack", folder / "manual")
        value = preview(
            self.project, "retire", links=[str(folder / "manual")], root=self.engine
        )
        execute(
            self.project,
            "retire",
            links=[str(folder / "manual")],
            expect=value["plan_digest"],
            root=self.engine,
        )
        self.assertFalse(os.path.lexists(folder / "manual"))
        self.assertTrue((self.project / "behavior_pack/manifest.json").is_file())

    def test_real_directory_is_never_retired(self):
        folder = self.engine / "behavior_packs/manual"
        shutil.copytree(self.project / "behavior_pack", folder)
        plan = preview(self.project, "retire", links=[str(folder)], root=self.engine)
        self.assertFalse(plan["can_apply"])
        self.assertTrue((folder / "manifest.json").exists())

    def test_uuid_reservation_blocks_only_intersecting_packages(self):
        dep, _pack = self.publish(transaction="pending")
        other = fixture(self.root, "unrelated")
        self.publish(other)
        duplicate = fixture(self.root, "duplicate")
        shutil.copyfile(
            self.project / "behavior_pack/manifest.json",
            duplicate / "behavior_pack/manifest.json",
        )
        with self.assertRaises(EngineError) as error:
            self.publish(duplicate)
        self.assertEqual(error.exception.code, "busy")
        with dep.lock():
            dep.rollback()

    def test_rollback_preserves_other_projects_publication(self):
        dep, _ = self.publish(transaction="pending")
        other = fixture(self.root, "later")
        self.publish(other)
        with dep.lock():
            dep.rollback()
        self.assertTrue(
            all(
                e["project"] == str(other)
                for e in storage.read(self.manager.path)["links"].values()
            )
        )
        self.assertEqual(len(storage.read(self.manager.ownership_path)["links"]), 2)

    def test_external_link_change_prevents_any_partial_rollback(self):
        dep, _ = self.publish(transaction="pending")
        links = storage.read(self.manager.path)["links"]
        key = next(iter(links))
        from mcpywrap_core.mcstudio.deployment_links import unlink

        unlink(self.engine / key)
        directory_link(self.project, self.engine / key)
        before = storage.read(self.manager.path)
        with dep.lock(), self.assertRaises(EngineError):
            dep.rollback()
        self.assertEqual(storage.read(self.manager.path), before)
        self.assertEqual((self.engine / key).resolve(), self.project)

    def test_unknown_game_process_blocks_migration_without_killing_it(self):
        child, sid = self.split()
        process = Mock(pid=9876, info={"pid": 9876, "name": "Minecraft.Windows.exe"})
        with patch("psutil.process_iter", return_value=[process]):
            value = preview(child, "migrate", self.project, sid, root=self.engine)
        self.assertFalse(value["can_apply"])
        self.assertEqual(value["blockers"][0]["state"], "unknown")
        process.terminate.assert_not_called()

    def test_link_snapshot_restores_dangling_junction_without_source_creation(self):
        source = self.root / "source"
        source.mkdir()
        link = self.root / "link"
        directory_link(source, link)
        state = capture(link)
        from mcpywrap_core.mcstudio.deployment_links import unlink

        unlink(link)
        source.rmdir()
        restore(link, state)
        self.assertTrue(os.path.lexists(link))
        self.assertFalse(source.exists())

    def test_cli_inspect_is_read_only_and_remote_never_falls_back(self):
        self.legacy()
        runner = CliRunner()
        with patch(
            "mcpywrap_core.runtime.deployment_service.global_root", return_value=self.engine
        ), patch("mcpywrap_core.engines.host.describe", return_value={"backend": "windows"}):
            result = runner.invoke(
                cli,
                [
                    "--local",
                    "--project",
                    str(self.project),
                    "deployment",
                    "inspect",
                    "--json",
                ],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout)["state"], "preview")
            result = runner.invoke(
                cli,
                [
                    "--remote",
                    "http://127.0.0.1:1",
                    "--project",
                    str(self.project),
                    "deployment",
                    "repair",
                    "--apply",
                    "--json",
                ],
            )
            self.assertNotEqual(result.exit_code, 0)
        self.assertFalse(self.manager.path.exists())

    def test_repair_preserves_published_identity_when_source_uuid_changes(self):
        self.publish()
        before = storage.read(self.manager.path)["links"]
        source = self.project / "behavior_pack/manifest.json"
        value = storage.read(source)
        value["header"]["uuid"] = "12345678-1234-5678-1234-567812345678"
        storage.write(source, value)
        plan = preview(self.project, "repair", root=self.engine)
        execute(self.project, "repair", expect=plan["plan_digest"], root=self.engine)
        self.assertEqual(storage.read(self.manager.path)["links"], before)

    def test_recovery_preview_accepts_known_partial_ledger_commit(self):
        self.publish()
        (self.project / "behavior_pack/main.py").write_text(
            "VALUE = 2", encoding="utf-8"
        )
        dep, _ = self.publish(transaction="pending")
        pending = self.manager.transaction_path(dep.journal["id"])
        journal = storage.read(pending)
        old = storage.read(self.manager.ownership_path)
        for change in journal["ledger_changes"]:
            if change["old"] is None:
                old[change["section"]].pop(change["key"], None)
            else:
                old[change["section"]][change["key"]] = change["old"]
        storage.write(self.manager.ownership_path, old)
        dead = {"pid": 99999999, "created_at": 0, "executable": "missing"}
        journal["owner"] = dead
        storage.write(pending, journal)
        local = storage.read(dep.journal_path)
        local["owner"] = dead
        storage.write(dep.journal_path, local)
        plan = preview(self.project, "repair", root=self.engine)
        self.assertTrue(plan["can_apply"], plan)
        execute(self.project, "repair", expect=plan["plan_digest"], root=self.engine)
        self.assertIn(
            b"VALUE = 1",
            (
                self.project / ".mcpy/runtime/assembled/behavior_pack/main.py"
            ).read_bytes(),
        )
        self.assertFalse(pending.exists())

    def test_explicit_foreign_retirement_observes_foreign_session(self):
        from mcpywrap_core.mcstudio.processes import identity

        other = fixture(self.root, "foreign")
        self.publish(other)
        key = next(iter(storage.read(self.manager.path)["links"]))
        storage.write(
            other / ".runtime/sessions" / ("f" * 32) / "session.json",
            {
                "session": "f" * 32,
                "state": "running",
                "project": str(other),
                "game": identity(os.getpid()),
            },
        )
        plan = preview(
            self.project, "retire", links=[str(self.engine / key)], root=self.engine
        )
        self.assertFalse(plan["can_apply"])
        self.assertEqual(plan["blockers"][0]["project"], str(other))

    def test_directory_move_migrates_owned_dangling_links_without_recreating_old_root(
        self,
    ):
        self.publish()
        sid = "d" * 32
        storage.write(
            self.project / ".runtime/sessions" / sid / "session.json",
            {
                "session": sid,
                "project": str(self.project),
                "mode": "local",
                "backend": "windows",
                "state": "failed",
                "game": None,
                "level_id": "world",
            },
        )
        original = self.project
        moved = self.root / "moved"
        original.rename(moved)
        plan = preview(moved, "migrate", original, sid, root=self.engine)
        self.assertTrue(plan["can_apply"], plan)
        self.assertEqual(len(plan["conflicts"]), 2)
        self.publish(
            moved,
            migration={"from": str(original), "expect": plan["inspection_digest"]},
        )
        self.assertFalse(original.exists())
        receipt = storage.read(moved / ".runtime/deployment-owner.json")
        self.assertEqual(receipt["project"], str(moved))
        self.assertTrue(
            all(
                e["project"] == str(moved)
                for e in storage.read(self.manager.path)["links"].values()
            )
        )

    def test_retire_rechecks_snapshot_after_acquiring_global_lock(self):
        from contextlib import contextmanager

        from mcpywrap_core.mcstudio.deployment_links import unlink

        link = self.engine / "behavior_packs/manual"
        link.parent.mkdir(parents=True)
        directory_link(self.project / "behavior_pack", link)
        other = fixture(self.root, "concurrent")
        plan = preview(self.project, "retire", links=[str(link)], root=self.engine)
        original = ManagedLinks.lock
        changed = []

        @contextmanager
        def competing(manager):
            with original(manager):
                if not changed:
                    changed.append(True)
                    unlink(link)
                    directory_link(other / "behavior_pack", link)
                yield

        with (
            patch.object(ManagedLinks, "lock", competing),
            self.assertRaises(EngineError) as error,
        ):
            execute(
                self.project,
                "retire",
                links=[str(link)],
                expect=plan["plan_digest"],
                root=self.engine,
            )
        self.assertEqual(error.exception.code, "plan_stale")
        self.assertEqual(link.resolve(), other / "behavior_pack")

    def test_group_migration_binds_recipe_and_rewrites_recovery_target(self):
        from mcpywrap_core.runtime import groups

        child, sid = self.split()
        backend = Mock(id="windows")
        record = groups._new(child, backend, "local", {"options": {}, "overrides": {}})
        record["members"][0].update(session=sid, state="failed")
        groups.save(record)
        with self.assertRaises(EngineError) as error:
            preview(child, "migrate", self.project, sid, root=self.engine)
        self.assertEqual(error.exception.code, "group_required")
        plan = preview(
            child, "migrate", self.project, group=record["group"], root=self.engine
        )
        record["recipe"]["options"]["new"] = True
        groups.save(record)
        with self.assertRaises(EngineError) as error:
            groups.restart(
                child,
                group=record["group"],
                migration={"group_expect": plan["group_expect"]},
            )
        self.assertEqual(error.exception.code, "plan_stale")
        groups._set_failure(
            record,
            EngineError(
                "duplicate",
                "pack_conflict",
                actions=[
                    {
                        "kind": "migrate",
                        "argv": ["mcpy", "deployment", "migrate", "--session", sid],
                    }
                ],
            ),
        )
        self.assertNotIn("--session", record["actions"][0]["argv"])
        self.assertEqual(
            record["actions"][0]["argv"][-2:], ["--group", record["group"]]
        )

    def test_launch_journal_uses_canonical_global_root(self):
        from mcpywrap_core.mcstudio.deployment_links import unlink

        self.engine.mkdir()
        alias = self.root / "engine-alias"
        directory_link(self.engine, alias)
        deployment = Deployment(self.project)
        with deployment.lock():
            pack = deployment.prepare()
            deployment.begin_launch()
            deployment.publish_links(alias, [pack])
            self.assertEqual(deployment.journal["links"]["root"], str(self.engine))
            unlink(alias)
            deployment.rollback()
        self.assertFalse(alias.exists())
        self.assertEqual(storage.read(self.manager.path)["links"], {})


class DiagnosticTests(unittest.TestCase):
    def test_worker_persists_and_prints_full_launch_diagnostic(self):
        from contextlib import redirect_stderr
        from io import StringIO

        from mcpywrap_core.mcstudio import session_worker

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            sid = "a" * 32
            directory = project / ".runtime/sessions" / sid
            storage.write(
                directory / "session.json",
                {
                    "state": "starting",
                    "mode": "local",
                    "backend": "windows",
                    "game": None,
                    "created_at": 1,
                    "level_id": "world",
                    "log_path": str(directory / "game.log"),
                },
            )
            backend = Mock()
            backend.launch.side_effect = EngineError(
                "duplicate",
                "pack_conflict",
                "inspect first",
                conflicts=[
                    {
                        "kind": "behavior",
                        "uuid": "a",
                        "path": "old-path",
                        "source": "new-path",
                    }
                ],
                actions=[{"argv": ["mcpy", "deployment", "inspect"]}],
            )
            output = StringIO()
            with (
                patch("mcpywrap_core.engines.backend.get_backend", return_value=backend),
                patch.object(session_worker, "FileLogServer"),
                redirect_stderr(output),
            ):
                session_worker.run(project, sid)
            value = storage.read(directory / "session.json")
            self.assertEqual(value["details"]["conflicts"][0]["path"], "old-path")
            self.assertEqual(value["hint"], "inspect first")
            self.assertIn("old-path", output.getvalue())
            self.assertEqual(value["actions"][0]["argv"][0], "mcpy")

    def test_details_and_actions_survive_round_trip_and_redaction(self):
        from mcpywrap_core.runtime.diagnostics import diagnostic, exception

        source = EngineError(
            "secret token",
            "pack_conflict",
            "secret hint",
            conflicts=[
                {"kind": "behavior", "uuid": "a", "path": "old", "source": "new"}
            ],
            actions=[{"argv": ["mcpy", "deployment", "inspect"]}],
            token="secret",
        )
        value = diagnostic(source, ["secret"])
        restored = exception(json.loads(json.dumps(value)))
        self.assertEqual(restored.code, "pack_conflict")
        self.assertEqual(restored.details["conflicts"][0]["path"], "old")
        self.assertNotIn("secret", json.dumps(value))
        self.assertEqual(restored.details["actions"][0]["argv"][0], "mcpy")


if __name__ == "__main__":
    unittest.main()
