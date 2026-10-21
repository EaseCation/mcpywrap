"""Real GBK subprocesses and strict GBK streams, without enabling UTF-8 mode."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_runtime_deployment import directory_link, fixture

from mcpywrap.runtime import storage
from mcpywrap.utils.console import echo


class DeploymentEncodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = fixture(self.root, "中文🧪项目")
        self.repo = Path(__file__).resolve().parents[1]
        self.appdata = self.root / "用户资料"
        self.global_root = self.appdata / "MinecraftPE_Netease/games/com.netease"
        self.env = dict(
            os.environ,
            PYTHONPATH=str(self.repo),
            PYTHONUTF8="0",
            PYTHONIOENCODING="gbk",
            APPDATA=str(self.appdata),
        )

    def call(self, *arguments, command="deployment"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mcpywrap",
                "--local",
                "--project",
                str(self.project),
                "--non-interactive",
                *([command] if command else []),
                *arguments,
            ],
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            check=False,
            timeout=45,
        )
        return (
            result.returncode,
            result.stdout.decode("gbk"),
            result.stderr.decode("gbk"),
        )

    @unittest.skipUnless(os.name == "nt", "Windows global deployment commands")
    def test_gbk_json_round_trip_and_utf8_persistent_records(self):
        code, output, error = self.call("inspect", "--json")
        self.assertEqual(code, 0, error)
        value = json.loads(output)
        self.assertEqual(value["project"], str(self.project.resolve()))
        self.assertTrue(output.isascii())
        self.assertFalse(self.global_root.exists())
        code, output, _ = self.call("repair", "--json")
        plan = json.loads(output)
        self.assertEqual(code, 0)
        code, output, error = self.call(
            "repair", "--apply", "--expect", plan["plan_digest"], "--json"
        )
        self.assertEqual(code, 0, error + output)
        path = self.project / ".runtime/deployment-owner.json"
        value = json.loads(path.read_bytes().decode("utf-8"))
        self.assertEqual(value["project"], str(self.project.resolve()))
        self.assertIn("🧪", path.read_text(encoding="utf-8"))
        code, output, error = self.call("inspect", "--json")
        self.assertEqual(code, 0, error)
        self.assertEqual(json.loads(output)["issues"], [])

    @unittest.skipUnless(os.name == "nt", "Windows global deployment commands")
    def test_gbk_human_preview_preserves_chinese_and_escapes_unsupported_glyphs(self):
        code, output, error = self.call("repair")
        self.assertEqual(code, 0, error)
        self.assertIn("项目", output)
        self.assertIn(r"\U0001f9ea", output)
        self.assertIn("--expect", output)
        self.assertNotIn("UnicodeEncodeError", error)

    @unittest.skipUnless(os.name == "nt", "Windows global deployment commands")
    def test_gbk_interactive_confirmation_and_completion(self):
        # Use real GBK input/output streams; emulate only the terminal detection.
        script = (
            "from unittest.mock import patch\n"
            "from mcpywrap.__main__ import main\n"
            "with patch('mcpywrap.command_context.human_interaction', return_value=True):\n"
            "    main()\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                "--local",
                "--project",
                str(self.project),
                "deployment",
                "repair",
                "--interactive",
            ],
            input=b"y\n",
            env=self.env,
            cwd=self.repo,
            capture_output=True,
            timeout=45,
            check=False,
        )
        output, error = result.stdout.decode("gbk"), result.stderr.decode("gbk")
        self.assertEqual(result.returncode, 0, error + output)
        self.assertIn("确认执行以上部署修复", output)
        self.assertIn("部署修复已完成", output)
        self.assertNotIn("--expect", output)
        self.assertNotIn("UnicodeEncodeError", error)
        identity = storage.read(self.project / ".runtime/deployment-owner.json")
        self.assertEqual(identity["project"], str(self.project.resolve()))

    @unittest.skipUnless(os.name == "nt", "Windows global deployment commands")
    def test_gbk_conflict_details_keep_unicode_paths_in_ascii_json(self):
        old = fixture(self.root, "旧项目🧪")
        refs = {}
        for kind in ("behavior", "resource"):
            shutil.copyfile(
                self.project / (kind + "_pack/manifest.json"),
                old / (kind + "_pack/manifest.json"),
            )
            link = self.global_root / (kind + "_packs") / ("历史_" + kind)
            link.parent.mkdir(parents=True, exist_ok=True)
            directory_link(old / (kind + "_pack"), link)
            refs[kind + "_packs"] = [link.name]
        storage.write(old / ".runtime/old.cppconfig", {"world_info": refs})
        code, output, error = self.call("repair", "--json")
        self.assertEqual(code, 0, error)
        plan = json.loads(output)
        self.assertEqual(len(plan["conflicts"]), 2)
        self.assertTrue(
            all(e["project"] == str(old.resolve()) for e in plan["conflicts"])
        )
        code, output, error = self.call(
            "repair", "--apply", "--expect", plan["plan_digest"], "--json"
        )
        self.assertNotEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(result["code"], "pack_conflict")
        self.assertIn("🧪", result["details"]["conflicts"][0]["source"])
        self.assertNotIn("UnicodeEncodeError", error)

    @unittest.skipUnless(os.name == "nt", "Windows global deployment commands")
    def test_committed_plan_survives_process_exit_before_response(self):
        code, output, error = self.call("repair", "--json")
        self.assertEqual(code, 0, error)
        plan = json.loads(output)
        injection = self.root / "injection"
        injection.mkdir()
        (injection / "sitecustomize.py").write_text(
            "import os\nif os.environ.get('MCPY_EXIT_AFTER_COMMIT') == '1':\n"
            "    from mcpywrap.mcstudio.deployment_links import ManagedLinks\n"
            "    original = ManagedLinks.commit\n"
            "    def commit(self, transaction):\n"
            "        original(self, transaction)\n"
            "        os._exit(77)\n"
            "    ManagedLinks.commit = commit\n",
            encoding="utf-8",
        )
        previous = self.env
        self.env = dict(
            previous,
            PYTHONPATH=str(injection) + os.pathsep + str(self.repo),
            MCPY_EXIT_AFTER_COMMIT="1",
        )
        code, _, _ = self.call(
            "repair", "--apply", "--expect", plan["plan_digest"], "--json"
        )
        self.assertEqual(code, 77)
        self.env = previous
        code, output, error = self.call(
            "repair", "--apply", "--expect", plan["plan_digest"], "--json"
        )
        self.assertEqual(code, 0, error + output)
        self.assertEqual(json.loads(output)["state"], "already_applied")

    @unittest.skipUnless(os.name == "nt", "Windows local startup")
    def test_default_gbk_run_guides_existing_failure_without_worker(self):
        old = fixture(self.root, "旧项目")
        refs = {}
        for kind in ("behavior", "resource"):
            shutil.copyfile(
                self.project / (kind + "_pack/manifest.json"),
                old / (kind + "_pack/manifest.json"),
            )
            link = self.global_root / (kind + "_packs") / ("历史_" + kind)
            link.parent.mkdir(parents=True, exist_ok=True)
            directory_link(old / (kind + "_pack"), link)
            refs[kind + "_packs"] = [link.name]
        storage.write(old / ".runtime/old.cppconfig", {"world_info": refs})
        sid = "a" * 32
        path = self.project / ".runtime/sessions" / sid / "session.json"
        storage.write(
            path,
            {
                "session": sid,
                "project": str(self.project),
                "state": "failed",
                "mode": "local",
                "backend": "windows",
                "code": "pack_conflict",
                "error": "全局包 UUID 冲突",
                "level_id": "world",
            },
        )
        storage.write(
            self.project / ".runtime/instances/world.json",
            {
                "level_id": "world",
                "state": "failed",
                "last_session": sid,
                "name": "旧失败",
                "created_at": 1,
            },
        )
        before = path.read_bytes()
        code, output, error = self.call(
            "run", "--no-gui", "--detach", "--json", command=None
        )
        self.assertEqual(code, 1, error + output)
        value = json.loads(output)
        self.assertEqual(value["code"], "pack_conflict")
        self.assertEqual(len(value["details"]["conflicts"]), 2)
        self.assertTrue(output.isascii())
        self.assertTrue(any(a.get("kind") == "migrate" for a in value["actions"]))
        code, output, error = self.call("run", "--no-gui", "--detach", command=None)
        self.assertEqual(code, 1)
        self.assertIn("只读预览", error)
        self.assertIn("migrate", error)
        self.assertIn(sid, error)
        self.assertNotIn("UnicodeEncodeError", error)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(path.parent.parent.iterdir())), 1)

    def test_strict_gbk_stream_keeps_encoding_and_does_not_raise(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
        echo("中文路径 🧪", file=stream)
        stream.flush()
        self.assertEqual(stream.encoding, "gbk")
        self.assertEqual(stream.errors, "strict")
        self.assertEqual(
            raw.getvalue().decode("gbk"), "中文路径 \\U0001f9ea" + os.linesep
        )


if __name__ == "__main__":
    unittest.main()
