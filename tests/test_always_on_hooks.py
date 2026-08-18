import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AlwaysOnHookTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.plugin_root = Path(self.temp_dir.name) / "plugin"
        shutil.copytree(ROOT / "hooks", self.plugin_root / "hooks")
        shutil.copytree(ROOT / "skills", self.plugin_root / "skills")
        self.config_dir = Path(self.temp_dir.name) / "claude config"
        self.config_dir.mkdir()

    def runtimes(self):
        runtimes = []
        if node := shutil.which("node"):
            runtimes.append(("node", [node, self.plugin_root / "hooks" / "always-on.mjs"]))
        if sh := shutil.which("sh"):
            runtimes.append(("sh", [sh, self.plugin_root / "hooks" / "always-on.sh"]))
        if powershell := shutil.which("pwsh") or shutil.which("powershell"):
            runtimes.append(
                (
                    "powershell",
                    [
                        powershell,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        self.plugin_root / "hooks" / "always-on.ps1",
                    ],
                )
            )
        return runtimes

    def run_hook(self, command, payload=None):
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        # Always hand the hook a closed stdin. Claude Code writes a payload and
        # closes the pipe; a test that let the runner's own stdin through would
        # leave the hooks that read it waiting on a pipe nobody closes.
        return subprocess.run(
            [str(part) for part in command],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            input="" if payload is None else json.dumps(payload),
        )

    @staticmethod
    def normalize(stdout):
        # The banner embeds the flag path. On Windows the sh runtime joins it
        # with "/" while node and PowerShell join with "\"; both name the same
        # file, so unify separators (and newlines) before comparing runtimes.
        return stdout.replace("\r\n", "\n").replace("\\", "/")

    def test_hook_is_silent_without_opt_in_flag(self):
        self.assertTrue(self.runtimes(), "no hook runtime is available")

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual("", result.stderr)

    def test_runtimes_strip_frontmatter_with_trailing_whitespace(self):
        skill_path = self.plugin_root / "skills" / "i-have-adhd" / "SKILL.md"
        skill_path.write_text("---   \nname: fixture\n--- \t\nFixture body.\n")
        (self.config_dir / ".i-have-adhd-always").touch()
        outputs = {}

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                normalized = self.normalize(result.stdout)
                self.assertNotIn("name: fixture", normalized)
                self.assertIn("\n\nFixture body.\n", normalized)
                outputs[name] = normalized

        self.assertEqual(1, len(set(outputs.values())))

    def test_runtimes_keep_content_when_frontmatter_is_unclosed(self):
        # An opening --- with no closing delimiter is not frontmatter. Keeping
        # the whole file beats injecting a banner that promises "the ruleset
        # below" followed by nothing.
        skill_path = self.plugin_root / "skills" / "i-have-adhd" / "SKILL.md"
        skill_path.write_text("---\nname: fixture\nFixture body, fence never closed.\n")
        (self.config_dir / ".i-have-adhd-always").touch()
        outputs = {}

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                normalized = self.normalize(result.stdout)
                self.assertIn("Fixture body, fence never closed.", normalized)
                outputs[name] = normalized

        self.assertEqual(1, len(set(outputs.values())))

    def test_runtimes_strip_an_empty_frontmatter_block(self):
        # An opening --- immediately followed by the closing --- is a valid but
        # empty frontmatter block. The Node regex required a newline before the
        # closing delimiter, so it left the block in place while the sh and
        # PowerShell hooks stripped it — a parity gap the other cases missed.
        skill_path = self.plugin_root / "skills" / "i-have-adhd" / "SKILL.md"
        skill_path.write_text("---\n---\nFixture body.\n")
        (self.config_dir / ".i-have-adhd-always").touch()
        outputs = {}

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                normalized = self.normalize(result.stdout)
                self.assertNotIn("\n---\n", normalized)
                self.assertIn("\n\nFixture body.\n", normalized)
                outputs[name] = normalized

        self.assertEqual(1, len(set(outputs.values())))

    def test_hook_uses_shell_free_node_exec_form(self):
        config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        hook = config["hooks"]["SessionStart"][0]["hooks"][0]

        self.assertEqual("node", hook["command"])
        self.assertEqual(
            ["${CLAUDE_PLUGIN_ROOT}/hooks/always-on.mjs"],
            hook["args"],
        )

    def test_runtimes_stay_silent_for_a_session_turned_off(self):
        # SessionStart fires again on resume and compaction, so a mid-session
        # "stop adhd mode" is only worth anything if the re-injection honours it.
        (self.config_dir / ".i-have-adhd-always").touch()
        (self.config_dir / ".i-have-adhd-off-session-one").touch()

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(
                    command, {"session_id": "session-one", "source": "compact"}
                )
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual("", result.stderr)

    def test_runtimes_inject_for_a_session_that_was_not_turned_off(self):
        # The marker is named after one session so it cannot silence another
        # running beside it.
        (self.config_dir / ".i-have-adhd-always").touch()
        (self.config_dir / ".i-have-adhd-off-session-one").touch()

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(
                    command, {"session_id": "session-two", "source": "compact"}
                )
                self.assertEqual(0, result.returncode)
                self.assertIn("ADHD MODE ACTIVE", self.normalize(result.stdout))
                self.assertEqual("", result.stderr)

    def test_runtimes_inject_when_the_payload_names_no_session(self):
        # A payload the hook cannot read leaves it no session to check, and
        # staying silent then would suppress the ruleset for a user who never
        # asked for that. Injecting is the behaviour this check was added to.
        (self.config_dir / ".i-have-adhd-always").touch()
        (self.config_dir / ".i-have-adhd-off-session-one").touch()

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertIn("ADHD MODE ACTIVE", self.normalize(result.stdout))
                self.assertEqual("", result.stderr)


class SessionStateHookTest(unittest.TestCase):
    """The UserPromptSubmit hook: records the phrase that turns the mode off."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.plugin_root = Path(self.temp_dir.name) / "plugin"
        shutil.copytree(ROOT / "hooks", self.plugin_root / "hooks")
        self.config_dir = Path(self.temp_dir.name) / "claude config"
        self.config_dir.mkdir()
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("this hook has no shell fallback, so it needs node")

    def run_hook(self, prompt, session_id="session-one"):
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        return subprocess.run(
            [self.node, str(self.plugin_root / "hooks" / "session-state.mjs")],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            input=json.dumps({"session_id": session_id, "prompt": prompt}),
        )

    def marker(self, session_id="session-one"):
        return self.config_dir / (".i-have-adhd-off-" + session_id)

    def test_records_the_off_phrase_against_the_session(self):
        (self.config_dir / ".i-have-adhd-always").touch()

        result = self.run_hook("stop adhd mode")

        self.assertEqual(0, result.returncode)
        self.assertTrue(self.marker().exists())
        self.assertEqual("", result.stdout)

    def test_the_skill_invocation_turns_it_back_on(self):
        (self.config_dir / ".i-have-adhd-always").touch()
        self.marker().touch()

        result = self.run_hook("/i-have-adhd")

        self.assertEqual(0, result.returncode)
        self.assertFalse(self.marker().exists())

    def test_quoted_and_fenced_text_is_discussion_not_instruction(self):
        # The phrase appears in this project's own docs, in the ruleset the
        # SessionStart hook injects, and in any conversation about the plugin.
        # Acting on a quotation would turn the mode off for talking about it.
        (self.config_dir / ".i-have-adhd-always").touch()

        for prompt in ('the docs say "stop adhd mode" somewhere', "run `normal mode`"):
            with self.subTest(prompt=prompt):
                result = self.run_hook(prompt)
                self.assertEqual(0, result.returncode)
                self.assertFalse(self.marker().exists())

    def test_a_session_id_that_is_not_a_plain_token_is_refused(self):
        # The id names a file. One carrying separators would place the marker
        # outside the config directory.
        (self.config_dir / ".i-have-adhd-always").touch()

        result = self.run_hook("stop adhd mode", session_id="../escaped")

        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual([], list(self.config_dir.glob(".i-have-adhd-off-*")))

    def test_hook_uses_shell_free_node_exec_form(self):
        config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        hook = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]

        self.assertEqual("node", hook["command"])
        self.assertEqual(
            ["${CLAUDE_PLUGIN_ROOT}/hooks/session-state.mjs"],
            hook["args"],
        )


if __name__ == "__main__":
    unittest.main()
