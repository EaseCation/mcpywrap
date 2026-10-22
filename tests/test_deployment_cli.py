"""Human terminal recovery uses the same inspected/digest-bound service as JSON."""

import json
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import test_deployment_recovery
from click.testing import CliRunner

from mcpywrap_core.cli import cli
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.runtime.deployment_service import preview


class DeploymentCliTests(unittest.TestCase):
    def setUp(self):
        profile = test_deployment_recovery.RecoveryTests()
        profile.setUp()
        self.addCleanup(profile.doCleanups)
        self.profile = profile
        self.project, self.sid = profile.historical_failure()
        self.base = ["--local", "--project", str(self.project)]
        self.runner = CliRunner()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            patch(
                "mcpywrap_core.runtime.deployment_service.global_root",
                return_value=profile.engine,
            )
        )
        stack.enter_context(
            patch(
                "mcpywrap_core.engines.host.describe", return_value={"backend": "windows"}
            )
        )
        stack.enter_context(
            patch(
                "mcpywrap_core.engines.backend.describe", return_value={"backend": "windows"}
            )
        )
        self.human = stack.enter_context(
            patch("mcpywrap_core.command_context.human_interaction", return_value=True)
        )
        self.execute = stack.enter_context(
            patch(
                "mcpywrap_core.runtime.deployment_service.execute",
                return_value={"session": "new-session", "state": "running"},
            )
        )

    def migrate(self, *extra, input=None):
        return self.runner.invoke(
            cli,
            self.base
            + [
                "deployment",
                "migrate",
                "--from",
                str(self.profile.project),
                "--session",
                self.sid,
                *extra,
            ],
            input=input,
        )

    def run_game(self, *extra, input=None):
        return self.runner.invoke(
            cli, self.base + ["run", "--no-gui", *extra], input=input
        )

    def test_preview_remains_read_only_and_offers_interactive_command(self):
        result = self.migrate()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("行为包 1 个、资源包 1 个", result.output)
        self.assertIn("--interactive", result.output)
        self.assertNotIn("确认迁移以上包并重试原世界？", result.output)
        self.execute.assert_not_called()

    def test_explicit_interactive_migration_binds_preview_digest(self):
        expected = preview(self.project, "migrate", self.profile.project, self.sid)
        result = self.migrate("--interactive", input="y\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(
            "默认",
            self.runner.invoke(
                cli, self.base + ["deployment", "migrate", "--help"]
            ).output,
        )
        self.assertIn("世界就绪后", result.output)
        self.assertIn("新会话：new-session", result.output)
        self.assertNotIn("plan_digest:", result.output)
        self.execute.assert_called_once_with(
            str(self.project),
            "migrate",
            str(self.profile.project),
            self.sid,
            None,
            (),
            expected["plan_digest"],
        )

    def test_default_no_cancels_and_keeps_original_history(self):
        path = self.project / ".runtime/sessions" / self.sid / "session.json"
        before = path.read_bytes()
        result = self.run_game("--detach", input="\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("已取消", result.output)
        self.assertEqual(result.output.count("迁移并重试预览"), 1)
        self.assertNotIn("错误: 全局包部署冲突", result.output)
        self.assertEqual(path.read_bytes(), before)
        self.execute.assert_not_called()

    def test_run_migrates_in_place_and_no_gui_never_imports_qt(self):
        qt_before = {
            name for name in sys.modules if name.startswith(("PyQt", "PySide"))
        }
        result = self.run_game("--detach", input="y\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output.count("确认迁移以上包并重试原世界？"), 1)
        self.assertNotIn("--expect", result.output)
        self.assertIn("new-session", result.output)
        self.assertEqual(
            qt_before,
            {name for name in sys.modules if name.startswith(("PyQt", "PySide"))},
        )
        self.execute.assert_called_once()

    def test_foreground_run_continues_to_watch_new_session(self):
        with patch(
            "mcpywrap_core.engines.tui.watch_session", return_value={"state": "exited"}
        ) as watch:
            result = self.run_game(input="y\n")
        self.assertEqual(result.exit_code, 0, result.output)
        watch.assert_called_once_with(str(self.project), "new-session")

    def test_blocker_explained_without_confirmation(self):
        original = preview(self.project, "migrate", self.profile.project, self.sid)
        original.update(
            can_apply=False,
            blockers=[
                {
                    "project": str(self.profile.project),
                    "session": "busy-session",
                    "state": "unknown",
                }
            ],
        )
        with patch(
            "mcpywrap_core.runtime.deployment_service.preview", return_value=original
        ):
            result = self.run_game("--detach", input="y\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("busy-session", result.output)
        self.assertIn("无法确认是否退出", result.output)
        self.assertNotIn("确认迁移以上包并重试原世界？", result.output)
        self.execute.assert_not_called()

    def test_json_and_unattended_run_never_prompt(self):
        self.human.return_value = False
        with patch("click.confirm", side_effect=AssertionError("must not prompt")):
            result = self.run_game("--detach", "--json")
            self.assertEqual(result.exit_code, 1, result.output)
            data = json.loads(result.stdout)
            self.assertEqual(data["code"], "pack_conflict")
            self.assertEqual(len(data["details"]["conflicts"]), 2)
            human = self.run_game("--detach")
        self.assertEqual(human.exit_code, 1)
        self.assertIn("只读预览", human.output)
        self.execute.assert_not_called()

    def test_interactive_rejected_without_terminal_or_with_apply(self):
        self.human.return_value = False
        result = self.migrate("--interactive", "--json")
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("交互终端", json.loads(result.stdout)["error"])
        self.human.return_value = True
        result = self.migrate("--interactive", "--apply")
        self.assertEqual(result.exit_code, 2)
        self.execute.assert_not_called()

    def test_stale_plan_reported_once_without_reprompt(self):
        self.execute.side_effect = EngineError(
            "部署现场或重试目标已变化，请重新预览。", "plan_stale"
        )
        result = self.run_game("--detach", input="y\n")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("重新预览", result.output)
        self.assertEqual(result.output.count("确认迁移以上包并重试原世界？"), 1)
        self.execute.assert_called_once()

    def test_group_retry_uses_group_target_and_foreground_watcher(self):
        from mcpywrap_core.runtime.deployment_service import startup_problem
        from mcpywrap_core.runtime.diagnostics import exception

        problem = startup_problem(self.project)
        for action in problem["actions"]:
            argv = action["argv"]
            if "--session" in argv:
                index = argv.index("--session")
                del argv[index : index + 2]
            argv += ["--group", "failed-group"]
        plan = preview(self.project, "migrate", self.profile.project, self.sid)
        self.execute.return_value = {
            "group": "new-group",
            "members": [],
            "state": "starting",
        }
        with (
            patch("mcpywrap_core.engines.backend.get_backend") as backend,
            patch(
                "mcpywrap_core.runtime.deployment_service.preview", return_value=plan
            ) as inspect,
            patch(
                "mcpywrap_core.engines.tui.watch_group", return_value={"state": "exited"}
            ) as watch,
        ):
            backend.return_value.capabilities = ()
            backend.return_value.run.side_effect = exception(problem)
            result = self.run_game(input="y\n")
        self.assertEqual(result.exit_code, 0, result.output)
        inspect.assert_called_once_with(
            str(self.project),
            "migrate",
            str(self.profile.project),
            None,
            "failed-group",
        )
        self.assertEqual(self.execute.call_args.args[3:5], (None, "failed-group"))
        watch.assert_called_once()

    def test_multiple_owners_not_silently_selected(self):
        from mcpywrap_core.commands.deployment_output import recover_run

        problem = {
            "actions": [
                {"kind": "migrate", "from": "old-a"},
                {"kind": "migrate", "from": "old-b"},
            ]
        }
        with patch("click.confirm", side_effect=AssertionError("must not prompt")):
            self.assertIsNone(recover_run(self.project, problem))
        self.execute.assert_not_called()

    def test_inspect_finds_existing_failed_target_but_remains_read_only(self):
        result = self.runner.invoke(cli, self.base + ["deployment", "inspect"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(self.sid, result.output)
        self.assertIn("实际目标", result.output)
        self.assertIn("归属证据", result.output)
        self.assertIn("--interactive", result.output)
        self.execute.assert_not_called()

    def test_each_command_only_exposes_relevant_options(self):
        result = self.runner.invoke(
            cli, self.base + ["deployment", "inspect", "--help"]
        )
        self.assertNotIn("--apply", result.output)
        self.assertNotIn("--link", result.output)
        result = self.runner.invoke(cli, self.base + ["deployment", "retire", "--help"])
        self.assertNotIn("--session", result.output)
        self.assertIn("--interactive", result.output)

    def test_help_available_on_other_platforms_but_mutations_rejected(self):
        with patch("mcpywrap_core.engines.host.describe", return_value={"backend": None}):
            help_result = self.migrate("--help")
            result = self.runner.invoke(
                cli, self.base + ["deployment", "inspect", "--json"]
            )
        self.assertEqual(help_result.exit_code, 0, help_result.output)
        self.assertEqual(json.loads(result.stdout)["code"], "unsupported_feature")
        self.execute.assert_not_called()

    def test_remote_refuses_execution_but_allows_help(self):
        base = [
            "--project",
            str(self.project),
            "--remote",
            "http://127.0.0.1:1",
            "deployment",
        ]
        help_result = self.runner.invoke(cli, base + ["migrate", "--help"])
        result = self.runner.invoke(cli, base + ["repair", "--json"])
        self.assertEqual(help_result.exit_code, 0, help_result.output)
        self.assertEqual(result.exit_code, 2, result.output)
        self.assertIn("不会操作本机代替远端", json.loads(result.stdout)["error"])
        self.execute.assert_not_called()
