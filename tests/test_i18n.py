import tempfile
import unittest
import tkinter as tk
from pathlib import Path
from unittest import mock

import i18n
import main
from log_tools import RemoteLogBrowser
from result_compare import ResultCompareDialog
from settings_manager import load_settings


class I18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("zh")

    def test_supported_languages(self):
        self.assertEqual(i18n.SUPPORTED_LANGUAGES, {"zh": "中文", "en": "English"})

    def test_translate_static_text(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("SSH连接"), "SSH Connection")
        self.assertEqual(i18n.tr("Docker部署"), "Docker Deployment")

    def test_unknown_text_falls_back_to_source(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("不存在的界面文本"), "不存在的界面文本")

    def test_chinese_language_returns_source(self):
        i18n.set_language("zh")
        self.assertEqual(i18n.tr("SSH连接"), "SSH连接")

    def test_invalid_language_falls_back_to_chinese(self):
        i18n.set_language("fr")
        self.assertEqual(i18n.get_language(), "zh")


class LanguageSwitchTests(unittest.TestCase):
    def test_language_switch_rebuilds_ui_and_persists_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path", return_value=settings_file):
                app = main.WizardApp()
                try:
                    self.assertEqual(app.language_var.get(), "中文")
                    self.assertEqual(app.step_buttons[0][1].cget("text"), "1. SSH连接")

                    app.language_var.set("English")
                    app._on_language_change()

                    self.assertEqual(i18n.get_language(), "en")
                    self.assertEqual(app.step_buttons[0][1].cget("text"), "1. SSH Connection")
                    self.assertEqual(app.prev_btn.cget("text"), "< Previous")
                    self.assertEqual(app.next_btn.cget("text"), "Next >")
                    self.assertEqual(app.language_var.get(), "English")
                    self.assertEqual(load_settings().get("language"), "en")
                finally:
                    app.root.destroy()

    def test_result_compare_dialog_uses_localized_labels(self):
        root = tk.Tk()
        try:
            i18n.set_language("en")
            dialog = ResultCompareDialog(root)
            texts = []

            def walk(widget):
                for child in widget.winfo_children():
                    try:
                        text = child.cget("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text)
                    except Exception:
                        pass
                    walk(child)

            walk(dialog.dialog)
            self.assertIn("File A (baseline):", texts)
            self.assertIn("Select CSV...", texts)
        finally:
            root.destroy()

    def test_remote_log_browser_uses_localized_labels(self):
        root = tk.Tk()

        class FakeSSH:
            connected = False

        try:
            i18n.set_language("en")
            browser = RemoteLogBrowser(root, FakeSSH())
            texts = []

            def walk(widget):
                for child in widget.winfo_children():
                    try:
                        text = child.cget("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text)
                    except Exception:
                        pass
                    walk(child)

            walk(browser.dialog)
            self.assertIn("Other server", texts)
            self.assertIn("Filter KV cache", texts)
        finally:
            root.destroy()


class DynamicMessageI18nTests(unittest.TestCase):
    """Dynamic popups and status messages must follow the selected language."""

    def tearDown(self):
        i18n.set_language("zh")

    def test_trf_translates_dynamic_templates(self):
        i18n.set_language("en")
        self.assertEqual(
            i18n.trf("已清理: {work_dir}", work_dir="/tmp/aisbench"),
            "Cleaned: /tmp/aisbench")
        self.assertEqual(
            i18n.trf("发现 {count} 个镜像，请选择AISBench镜像；如无合适镜像，请切换为上传tar包。", count=3),
            "Found 3 image(s). Select an AISBench image; if none is suitable, "
            "switch to uploading a tar package.")
        self.assertEqual(
            i18n.trf("测试完成!\n\nCSV: {csv}\n日志: {log}\n共 {count} 条记录",
                     csv="a.csv", log="logs", count=2),
            "Tests complete!\n\nCSV: a.csv\nLog: logs\n2 records in total")

    def test_messagebox_literals_are_translated(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("提示"), "Notice")
        self.assertEqual(i18n.tr("请先连接到远程主机"), "Please connect to the remote host first")
        self.assertEqual(i18n.tr("Docker容器尚未部署，是否继续?"),
                         "Docker container is not deployed yet. Continue?")
        self.assertEqual(i18n.tr("尚未生成测试用例，是否继续?"),
                         "No test cases generated yet. Continue?")
        self.assertEqual(i18n.tr("请完成镜像和模型路径选择"),
                         "Please finish image and model path selection")
        self.assertEqual(i18n.tr("请选择本地代码zip包 (或改用程序内置)"),
                         "Please select a local code zip package (or use built-in)")

    def test_next_step_warning_is_english(self):
        """Clicking Next without a connection must warn in English."""
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path", return_value=settings_file):
                app = main.WizardApp()
                try:
                    app.language_var.set("English")
                    app._on_language_change()
                    app.current_step = 0
                    app.ssh._connected = False
                    # Patch the underlying Tk messagebox so the i18n wrapper
                    # runs and we can assert the *translated* arguments.
                    with mock.patch("i18n.messagebox.showwarning") as warn:
                        app._next_step()
                    warn.assert_called_once_with(
                        "Notice", "Please connect to the remote host first")
                finally:
                    app.root.destroy()

    def test_exit_cleanup_popup_is_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path", return_value=settings_file):
                app = main.WizardApp()
                try:
                    app.language_var.set("English")
                    app._on_language_change()
                    app.work_dir_var.set("/tmp/aisbench_deploy")
                    docker = mock.Mock()
                    docker.container_name = "aisbench-test-abc"
                    docker.container_is_running.return_value = True
                    app.docker = docker
                    with mock.patch("i18n.messagebox.askyesnocancel") as ask:
                        ask.return_value = None
                        app._exit_check_cleanup()
                    args, kwargs = ask.call_args
                    self.assertEqual(args[0], "Cleanup reminder")
                    self.assertIn("The Docker container is still running!", args[1])
                    self.assertIn("Container: aisbench-test-abc", args[1])
                    self.assertIn("Temporary deploy directory leftovers: /tmp/aisbench_deploy", args[1])
                    self.assertIn("Clean up the remote environment before exiting?", args[1])
                finally:
                    app.root.destroy()

    def test_validate_config_errors_are_english(self):
        from config_manager import ConfigManager
        i18n.set_language("en")
        mgr = ConfigManager(docker=None)
        errors = mgr.validate_config({})
        self.assertIn("MODEL_NAME cannot be empty", errors)
        self.assertIn("MODEL_PATH cannot be empty", errors)
        self.assertIn("HOST_IP cannot be empty", errors)
        self.assertIn("HOST_PORT cannot be empty", errors)

        errors = mgr.validate_config({"host_port": "abc"})
        self.assertIn("HOST_PORT must be a number: abc", errors)

    def test_ssh_connect_messages_are_english(self):
        from ssh_manager import SSHManager
        i18n.set_language("en")
        mgr = SSHManager()
        with mock.patch("ssh_manager.paramiko.SSHClient") as client_cls:
            client_cls.side_effect = OSError("boom")
            ok, msg = mgr.connect("1.2.3.4", 22, "root", password="x")
        self.assertFalse(ok)
        self.assertEqual(msg, "Connection failed: boom")

        import paramiko
        mgr2 = SSHManager()
        with mock.patch("ssh_manager.paramiko.SSHClient") as client_cls:
            client_cls.side_effect = paramiko.AuthenticationException()
            ok, msg = mgr2.connect("1.2.3.4", 22, "root", password="x")
        self.assertFalse(ok)
        self.assertEqual(msg, "Authentication failed; check username/password/key")

        self.assertEqual(mgr.execute("ls"), (-1, "", "Not connected to the remote host"))


if __name__ == "__main__":
    unittest.main()
