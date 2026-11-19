"""sdk-ask-cgi.py の配置前提テスト（SPEC.lib.muse.execution-path 版3）。

AC-EP-009: ホームが書けない環境でも受付は例外で落ちず、理由付きで拒否する。
AC-EP-010: MUSE_SDK_BASE / MUSE_SDK_HOME で状態の置き場所と運用ホームを
           差し替えられ、承認側も同じ BASE を見る。
AC-EP-011: BASE を使う全スクリプトが同じ解決規則（MUSE_SDK_BASE 優先）を持つ。
"""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASK_CGI = ROOT / "muse" / "sdk-ask-cgi.py"
APPROVE = ROOT / "muse" / "sdk-approve.py"


def run_cgi(fields, env):
    body = urllib.parse.urlencode(fields)
    full_env = {"PATH": os.environ["PATH"],
                "CONTENT_LENGTH": str(len(body.encode("utf-8")))}
    full_env.update(env)
    return subprocess.run([sys.executable, str(ASK_CGI)], input=body,
                          capture_output=True, text=True, env=full_env)


class SdkAskCgiBaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_invalid_submission_with_unwritable_home_refuses_cleanly(self):
        # HOME が通常ファイル = その配下には何も作れない（root でも失敗する）
        home_file = self.root / "home-file"
        home_file.write_text("not a dir", encoding="utf-8")
        proc = run_cgi({"instruction": "", "profile": ":read-only"},
                       {"HOME": str(home_file)})
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("受け付けできませんでした", proc.stdout)

    def test_valid_submission_with_broken_base_refuses_cleanly(self):
        home = self.root / "home"
        (home / "sdk-ask-workspace").mkdir(parents=True)
        (home / ".local").write_text("blocked", encoding="utf-8")
        proc = run_cgi({"instruction": "テスト指示", "profile": ":read-only"},
                       {"HOME": str(home)})
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("受け付けできませんでした", proc.stdout)

    def test_base_override_registers_and_approve_sees_it(self):
        home_file = self.root / "home-file"
        home_file.write_text("not a dir", encoding="utf-8")
        base = self.root / "base"
        ops_home = self.root / "ops-home"
        (ops_home / "sdk-ask-workspace").mkdir(parents=True)
        env = {"HOME": str(home_file),
               "MUSE_SDK_BASE": str(base),
               "MUSE_SDK_HOME": str(ops_home)}
        proc = run_cgi({"instruction": "テスト指示", "profile": ":read-only"}, env)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("承認待ちとして受け付けました", proc.stdout)
        pending = list((base / "pending").glob("*.json"))
        self.assertEqual(len(pending), 1)
        self.assertEqual(stat.S_IMODE(pending[0].stat().st_mode), 0o600)
        self.assertTrue((base / "exec-audit.jsonl").is_file())
        # 承認側（別 HOME）でも同じ BASE の依頼が見える
        list_env = {"PATH": os.environ["PATH"], "HOME": str(self.root / "other"),
                    "MUSE_SDK_BASE": str(base)}
        out = subprocess.run([sys.executable, str(APPROVE), "list"],
                             capture_output=True, text=True, env=list_env)
        self.assertEqual(out.returncode, 0)
        self.assertIn(pending[0].stem, out.stdout)

    def test_workspace_validation_uses_sdk_home(self):
        base = self.root / "base"
        ops_home = self.root / "ops-home"
        (ops_home / "ws").mkdir(parents=True)
        other_home = self.root / "other-home"
        (other_home / "ws2").mkdir(parents=True)
        env = {"HOME": str(other_home),
               "MUSE_SDK_BASE": str(base),
               "MUSE_SDK_HOME": str(ops_home)}
        ok = run_cgi({"instruction": "テスト指示", "profile": ":read-only",
                      "workspace": str(ops_home / "ws")}, env)
        self.assertIn("承認待ちとして受け付けました", ok.stdout)
        ng = run_cgi({"instruction": "テスト指示", "profile": ":read-only",
                      "workspace": str(other_home / "ws2")}, env)
        self.assertIn("受け付けできませんでした", ng.stdout)


class DefaultWorkspaceTest(unittest.TestCase):
    """版4: 既定ワークスペースは BASE 配下。運用ホームが辿れなくても成立する。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_default_workspace_created_under_base(self):
        home_file = self.root / "home-file"
        home_file.write_text("not a dir", encoding="utf-8")
        base = self.root / "base"
        ops_home = self.root / "ops-home"
        ops_home.mkdir()
        env = {"HOME": str(home_file),
               "MUSE_SDK_BASE": str(base),
               "MUSE_SDK_HOME": str(ops_home)}
        proc = run_cgi({"instruction": "テスト指示", "profile": ":read-only"}, env)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("承認待ちとして受け付けました", proc.stdout)
        self.assertTrue((base / "workspace").is_dir())
        pending = list((base / "pending").glob("*.json"))
        self.assertEqual(len(pending), 1)
        import json
        record = json.loads(pending[0].read_text(encoding="utf-8"))
        self.assertEqual(record["workspace"], str(base / "workspace"))

    def test_statable_missing_workspace_is_refused(self):
        base = self.root / "base"
        ops_home = self.root / "ops-home"
        ops_home.mkdir()
        env = {"HOME": str(self.root / "home"),
               "MUSE_SDK_BASE": str(base),
               "MUSE_SDK_HOME": str(ops_home)}
        proc = run_cgi({"instruction": "テスト指示", "profile": ":read-only",
                        "workspace": str(ops_home / "nonexistent")}, env)
        self.assertIn("受け付けできませんでした", proc.stdout)
        self.assertIn("存在しません", proc.stdout)


class DeferredWorkspaceValidationTest(unittest.TestCase):
    """版4 (REQ-EP-035): stat できないワークスペースは受付で判定せず承認に委ねる。"""

    def test_unstatable_workspace_is_registered_not_refused(self):
        import shutil
        if not shutil.which("runuser"):
            self.skipTest("runuser が無い")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        os.chmod(root, 0o755)
        base = root / "base"
        base.mkdir()
        os.chown(base, 65534, 65534)  # nobody:nogroup
        ops_home = root / "ops-home"
        sealed = ops_home / "sealed"
        sealed.mkdir(parents=True)
        (sealed / "ws").mkdir()
        os.chmod(sealed, 0o700)  # root のみ。nobody は中を stat できない
        body = urllib.parse.urlencode(
            {"instruction": "テスト指示", "profile": ":read-only",
             "workspace": str(sealed / "ws")})
        env = {"PATH": os.environ["PATH"], "HOME": "/var/www",
               "MUSE_SDK_BASE": str(base), "MUSE_SDK_HOME": str(ops_home),
               "CONTENT_LENGTH": str(len(body.encode("utf-8")))}
        # nobody から読める場所へ実物をコピーして実行する（配置先の www-data が
        # lib を読めるのと同じ条件にするため。内容はリポジトリの実物そのまま）
        cgi_copy = root / "sdk-ask-cgi.py"
        cgi_copy.write_bytes(ASK_CGI.read_bytes())
        os.chmod(cgi_copy, 0o644)
        proc = subprocess.run(
            ["runuser", "-u", "nobody", "--", "env"] +
            [f"{k}={v}" for k, v in env.items()] +
            [sys.executable, str(cgi_copy)],
            input=body, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("承認待ちとして受け付けました", proc.stdout)
        import json
        pending = list((base / "pending").glob("*.json"))
        self.assertEqual(len(pending), 1)
        record = json.loads(pending[0].read_text(encoding="utf-8"))
        self.assertEqual(record["workspace"], str(sealed / "ws"))


class BaseResolutionPremiseTest(unittest.TestCase):
    def test_all_base_consumers_resolve_via_env(self):
        consumers = ["muse/sdk-ask-cgi.py", "muse/sdk-approve.py",
                     "muse/sdk-auto-approve.py", "muse/sdk-emergency-stop.sh",
                     "muse/exec-log.sh"]
        for rel in consumers:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("MUSE_SDK_BASE", text, rel)


if __name__ == "__main__":
    unittest.main()
