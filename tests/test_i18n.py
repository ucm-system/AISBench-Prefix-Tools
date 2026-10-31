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
            self.assertIn("Label A:", texts)
            self.assertIn("Label B:", texts)
            self.assertIn("Export comparison charts", texts)
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
                    # Patch the dialog entry point so the i18n wrapper runs
                    # and we can assert the *translated* arguments.
                    with mock.patch("i18n._show_dialog") as show:
                        app._next_step()
                    kind, title, message = show.call_args.args[:3]
                    self.assertEqual(kind, "warning")
                    self.assertEqual(title, "Notice")
                    self.assertEqual(
                        message, "Please connect to the remote host first")
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
                    with mock.patch("i18n._show_dialog") as ask:
                        ask.return_value = None
                        app._exit_check_cleanup()
                    args, _kwargs = ask.call_args
                    self.assertEqual(args[0], "askyesnocancel")
                    self.assertEqual(args[1], "Cleanup reminder")
                    self.assertIn("The Docker container is still running!", args[2])
                    self.assertIn("Container: aisbench-test-abc", args[2])
                    self.assertIn(
                        "Temporary deploy directory leftovers: /tmp/aisbench_deploy",
                        args[2])
                    self.assertIn(
                        "Clean up the remote environment before exiting?", args[2])
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


class LanguageSwitchPreservesStateTests(unittest.TestCase):
    """Language switching must only change presentation, never wizard state."""

    def tearDown(self):
        i18n.set_language("zh")

    def test_language_switch_keeps_step_and_login_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path", return_value=settings_file):
                app = main.WizardApp()
                try:
                    app.current_step = 1
                    app.conn_vars["host"].set("192.168.1.30")
                    app.conn_vars["port"].set("2222")
                    app.conn_vars["user"].set("deployer")
                    app.conn_password.set("secret-pass")
                    app.conn_key.set("C:/keys/id_rsa")
                    app.tar_path.set("D:/images/aisbench.tar")
                    app.zip_path.set("D:/code/test.zip")
                    app.model_path_var.set("/mnt/models/deepseek")
                    app.ssh._connected = True
                    app.conn_status_lbl.config(
                        text="Connected: 192.168.1.30:2222", fg="#16a34a")
                    app.status_lbl.config(text="● 已连接", fg="#16a34a")

                    app.language_var.set("English")
                    app._on_language_change()

                    self.assertEqual(app.current_step, 1)
                    self.assertEqual(app.conn_vars["host"].get(), "192.168.1.30")
                    self.assertEqual(app.conn_vars["port"].get(), "2222")
                    self.assertEqual(app.conn_vars["user"].get(), "deployer")
                    self.assertEqual(app.conn_password.get(), "secret-pass")
                    self.assertEqual(app.conn_key.get(), "C:/keys/id_rsa")
                    self.assertEqual(app.tar_path.get(), "D:/images/aisbench.tar")
                    self.assertEqual(app.zip_path.get(), "D:/code/test.zip")
                    self.assertEqual(app.model_path_var.get(), "/mnt/models/deepseek")
                    self.assertEqual(
                        app.conn_status_lbl.cget("text"),
                        "Connected: 192.168.1.30:2222")
                    self.assertEqual(app.status_lbl.cget("text"), "● Connected")

                    app.language_var.set("中文")
                    app._on_language_change()
                    self.assertEqual(app.current_step, 1)
                    self.assertEqual(app.conn_vars["host"].get(), "192.168.1.30")
                    self.assertEqual(app.conn_password.get(), "secret-pass")
                    self.assertEqual(app.status_lbl.cget("text"), "● 已连接")
                finally:
                    app.root.destroy()

    def test_language_switch_restores_results_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path", return_value=settings_file):
                app = main.WizardApp()
                try:
                    app.current_step = 4
                    app.deployed = True
                    app.local_output_var.set("D:/results/run1")
                    app.results_tree.insert("", tk.END, values=(
                        "4,096", "1,024", "10,000", "100", "50",
                        "12.34", "56.78", "0.12", "0.03", "9.87",
                        "85.2", "12.3"))
                    app.results_info_lbl.config(
                        text="1 records  |  CSV: r.csv  |  Log: logs")
                    app.config_status_lbl.config(
                        text="✓ Config saved and verified", fg="#16a34a")
                    app.deploy_btn.config(text="Redeploy")

                    app.language_var.set("English")
                    app._on_language_change()

                    self.assertEqual(app.current_step, 4)
                    self.assertEqual(app.local_output_var.get(), "D:/results/run1")
                    first = app.results_tree.get_children()[0]
                    self.assertEqual(
                        app.results_tree.item(first)["values"][0], "4,096")
                    self.assertEqual(
                        app.results_info_lbl.cget("text"),
                        "1 records  |  CSV: r.csv  |  Log: logs")
                    self.assertEqual(
                        app.config_status_lbl.cget("text"),
                        "✓ Config saved and verified")
                    self.assertEqual(app.deploy_btn.cget("text"), "Redeploy")
                    self.assertTrue(app.deployed)
                finally:
                    app.root.destroy()


class DialogButtonI18nTests(unittest.TestCase):
    """Dialog buttons (OK/Cancel/Yes/No) must follow the selected language."""

    def tearDown(self):
        i18n.set_language("zh")

    def test_button_definitions_by_language(self):
        i18n.set_language("zh")
        buttons, default, escape = i18n._dialog_buttons("askyesnocancel")
        self.assertEqual([b[0] for b in buttons], ["是", "否", "取消"])
        self.assertEqual(default, True)
        self.assertEqual(escape, None)

        i18n.set_language("en")
        buttons, default, escape = i18n._dialog_buttons("askyesnocancel")
        self.assertEqual([b[0] for b in buttons], ["Yes", "No", "Cancel"])

        buttons, default, escape = i18n._dialog_buttons("askyesno")
        self.assertEqual([b[0] for b in buttons], ["Yes", "No"])
        self.assertEqual(default, True)
        self.assertEqual(escape, False)

        buttons, default, escape = i18n._dialog_buttons("info")
        self.assertEqual([b[0] for b in buttons], ["OK"])
        self.assertEqual(escape, "ok")

    def _collect_button_texts(self, root):
        texts = []
        for child in root.winfo_children():
            if isinstance(child, tk.Toplevel):
                for sub in child.winfo_children():
                    for w in sub.winfo_children():
                        if isinstance(w, tk.Button):
                            texts.append(w.cget("text"))
        return texts

    def test_askyesno_renders_english_buttons(self):
        root = tk.Tk()
        try:
            i18n.set_language("en")
            with mock.patch.object(tk.Toplevel, "wait_window", lambda self: None):
                result = i18n.askyesno("Notice", "Continue?")
            # No button clicked -> escape semantics (False), dialog still open
            self.assertFalse(result)
            self.assertEqual(set(self._collect_button_texts(root)), {"Yes", "No"})
        finally:
            for child in root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
            root.destroy()

    def test_askyesno_renders_chinese_buttons(self):
        root = tk.Tk()
        try:
            i18n.set_language("zh")
            with mock.patch.object(tk.Toplevel, "wait_window", lambda self: None):
                result = i18n.askyesno("提示", "继续?")
            self.assertFalse(result)
            self.assertEqual(set(self._collect_button_texts(root)), {"是", "否"})
        finally:
            for child in root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
            root.destroy()

    def test_showinfo_renders_english_button(self):
        root = tk.Tk()
        try:
            i18n.set_language("en")
            with mock.patch.object(tk.Toplevel, "wait_window", lambda self: None):
                result = i18n.showwarning("Notice", "Check the settings")
            self.assertEqual(result, "ok")
            self.assertEqual(set(self._collect_button_texts(root)), {"OK"})
        finally:
            for child in root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
