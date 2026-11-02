import tempfile
import unittest
import tkinter as tk
import re
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
        self.assertEqual(i18n.tr("创建任务"), "Create Task")
        self.assertEqual(i18n.tr("仅部署容器"), "Deploy container only")

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
                    if isinstance(child, tk.Toplevel):
                        texts.append(child.title())
                    try:
                        text = child.cget("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
                    except Exception:
                        pass
                    walk(child)

            walk(dialog.dialog)
            self.assertIn("File A (baseline):", texts)
            self.assertIn("Select CSV...", texts)
            self.assertIn("Label A:", texts)
            self.assertIn("Label B:", texts)
            self.assertIn("Export comparison charts", texts)
            self.assertIn("TTFT average (ms)", texts)
            self.assertIn("■ Throughput", texts)
        finally:
            root.destroy()

    def test_remote_log_browser_uses_localized_labels(self):
        root = tk.Tk()

        class FakeSSH:
            connected = False

        try:
            i18n.set_language("en")
            browser = RemoteLogBrowser(root, FakeSSH())
            browser._open_viewer("cat /var/log/vllm.log", "hello")
            texts = []
            texts.append(browser.dialog.title())

            def walk(widget):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Toplevel):
                        texts.append(child.title())
                    try:
                        text = child.cget("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text.strip())
                    except Exception:
                        pass
                    walk(child)

            walk(browser.dialog)
            self.assertIn("Other server", texts)
            self.assertIn("Filter KV cache", texts)
            self.assertIn("Server", texts)
            self.assertIn("Current execution host (not connected)", texts)
            self.assertIn("Log source", texts)
            self.assertIn("Host file", texts)
            self.assertIn("File in container", texts)
            self.assertIn("Container log (docker logs)", texts)
            self.assertIn(
                "File browser (double-click to enter a directory, "
                "single-click to select a file)", texts)
            self.assertIn("View log", texts)
            self.assertIn("Fill parameters", texts)
            self.assertIn("Remote log tool - filter KV cache / view log", texts)
            self.assertIn("Log viewer", texts)
            self.assertIn("Source command:", texts)
            self.assertIn("Copy all", texts)
            self.assertIn(
                "Loaded content: 5 characters "
                "(files use the last 2MB; docker logs use the last 5000 lines)",
                texts)
            self.assertFalse(
                [text for text in texts if re.search(r"[\u4e00-\u9fff]", text)])
        finally:
            root.destroy()

    def test_remote_log_browser_dynamic_messages_are_english(self):
        i18n.set_language("en")
        self.assertEqual(
            i18n.trf("当前执行机 ({host}:{port})", host="10.0.0.1", port=22),
            "Current execution host (10.0.0.1:22)")
        self.assertEqual(
            i18n.trf("共 {count} 个运行中容器", count=3),
            "3 running container(s)")
        self.assertEqual(
            i18n.trf("已加载 {count} 项", count=12), "Loaded 12 item(s)")
        self.assertEqual(
            i18n.trf("当前文件: {path}", path="/var/log/vllm.log"),
            "Current file: /var/log/vllm.log")
        self.assertEqual(
            i18n.trf("单个DP组KV cache = {value:,} tokens", value=1234567),
            "KV cache per DP group = 1,234,567 tokens")
        self.assertEqual(
            i18n.trf("模型最大上下文 = {value:,} tokens", value=32768),
            "Model max context = 32,768 tokens")
        self.assertEqual(
            i18n.trf("查看失败: {message}", message="permission denied"),
            "View failed: permission denied")
        self.assertIn(
            "Loaded content: 5 characters",
            i18n.trf(
                "已加载内容: {chars} 字符 "
                "(文件取尾部 {file_mb}MB, docker logs 取尾部 {docker_lines} 行)",
                chars=5, file_mb=2, docker_lines=5000))


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
            i18n.trf("共 {count} 个镜像（筛选后 {shown} 个），请选择AISBench镜像；如无合适镜像，请切换为上传tar包。",
                     count=3, shown=2),
            "3 image(s) in total (2 after filtering). Select an AISBench image; "
            "if none is suitable, switch to uploading a tar package.")
        self.assertEqual(
            i18n.trf("测试完成!\n\nCSV: {csv}\n日志: {log}\n共 {count} 条记录",
                     csv="a.csv", log="logs", count=2),
            "Tests complete!\n\nCSV: a.csv\nLog: logs\n2 records in total")

    def test_messagebox_literals_are_translated(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("提示"), "Notice")
        self.assertEqual(i18n.tr("请先连接到远程主机"), "Please connect to the remote host first")
        self.assertEqual(i18n.tr("请选择本地代码zip包 (或改用程序内置)"),
                         "Please select a local code zip package (or use built-in)")

    def test_create_task_page_texts_are_english(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("任务资源（镜像 · 代码 · 模型）"),
                         "Task resources (image · code · model)")
        self.assertEqual(i18n.tr("测试参数与用例设计"),
                         "Test parameters and case design")
        self.assertEqual(i18n.tr("创建并执行任务"), "Create and run the task")
        self.assertEqual(i18n.tr("🚀 创建任务"), "🚀 Create Task")
        self.assertEqual(i18n.tr("任务执行与结果"), "Task execution and results")
        self.assertEqual(
            i18n.trf("自动: {model} @ {host}:{port} (可展开修改)",
                     model="ds", host="192.168.1.30", port="8000"),
            "Automatic: ds @ 192.168.1.30:8000 (expand to modify)")

    def test_test_state_labels_are_english(self):
        from docker_manager import describe_test_state

        i18n.set_language("en")
        self.assertEqual(i18n.tr("初始化"), "Initialized")
        self.assertEqual(i18n.tr("执行中"), "Running")
        self.assertEqual(i18n.tr("执行完成"), "Completed")
        self.assertEqual(i18n.tr("异常终止"), "Abnormally terminated")
        self.assertEqual(i18n.tr("异常终止(执行中断)"),
                         "Abnormally terminated (interrupted)")
        self.assertEqual(i18n.tr("未标记"), "Not marked")

        self.assertEqual(describe_test_state("initialized"), "Initialized")
        self.assertEqual(describe_test_state("running"), "Running")
        self.assertEqual(describe_test_state("completed"), "Completed")
        self.assertEqual(describe_test_state("abnormal"),
                         "Abnormally terminated")
        self.assertEqual(describe_test_state(None), "Not marked")
        self.assertEqual(describe_test_state("running", False),
                         "Abnormally terminated (interrupted)")

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
                    self.assertIn("Test task state: Not marked", args[2])
                    self.assertIn(
                        "create the task again (redeploy the container)", args[2])
                    self.assertIn(
                        "exiting directly will terminate it abnormally", args[2])
                finally:
                    app.root.destroy()

    def test_cleanup_reminder_is_english_with_state_and_redeploy_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path",
                            return_value=settings_file):
                app = main.WizardApp()
                try:
                    app.language_var.set("English")
                    app._on_language_change()
                    app.work_dir_var.set("/tmp/aisbench_deploy")
                    docker = mock.Mock()
                    docker.container_name = "aisbench-test-abc"
                    docker.read_test_state.return_value = "completed"
                    docker.container_is_running.return_value = True
                    app.docker = docker
                    with mock.patch("main.askyesno", return_value=False) as ask:
                        app._show_cleanup_reminder()
                    message = ask.call_args_list[0].args[1]
                    self.assertIn("Tests complete!", message)
                    self.assertIn("Test task state: Completed", message)
                    self.assertIn(
                        "Temporary deploy directory leftovers: /tmp/aisbench_deploy",
                        message)
                    self.assertIn(
                        "create the task again (redeploy the container)", message)
                    self.assertIn(
                        "the container will be removed after cleanup", message)
                finally:
                    app.root.destroy()

    def test_cleanup_confirm_is_english_with_state_and_redeploy_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path",
                            return_value=settings_file):
                app = main.WizardApp()
                try:
                    app.language_var.set("English")
                    app._on_language_change()
                    app.work_dir_var.set("/tmp/aisbench_deploy")
                    docker = mock.Mock()
                    docker.container_name = "aisbench-test-abc"
                    docker.read_test_state.return_value = "abnormal"
                    docker.container_is_running.return_value = True
                    app.docker = docker
                    with mock.patch("main.askyesno", return_value=False) as ask:
                        app._cleanup_environment()
                    message = ask.call_args.args[1]
                    self.assertIn("Docker container: aisbench-test-abc", message)
                    self.assertIn("Test task state: Abnormally terminated",
                                  message)
                    self.assertIn(
                        "To run test cases again after cleanup, "
                        "create the task again (redeploy the container).",
                        message)
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

    def test_test_case_table_and_calculation_details_are_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path", return_value=settings_file):
                app = main.WizardApp()
                try:
                    app.designer.set_kv_cache_info(1_000_000, 2, 8192)
                    app.designer.set_input_lengths([4096])
                    app.designer.set_output_lengths([1024])
                    app.designer.set_repeat_rate(0.8)
                    app.designer.set_request_rate(0)
                    app.designer.generate_test_cases()
                    app._refresh_test_tree()

                    self.assertIn("请求数(推荐)",
                                  app.test_tree.heading("data_rec")["text"])
                    self.assertIn("用例 1", app.calc_detail_text.get("1.0", "end-1c"))

                    app.language_var.set("English")
                    app._on_language_change()

                    self.assertEqual(
                        app.test_tree.heading("data_rec")["text"],
                        "Requests (recommended)")
                    self.assertEqual(
                        app.test_tree.heading("data_min")["text"],
                        "Requests (minimum)")
                    self.assertEqual(
                        app.test_tree.heading("concurrency")["text"],
                        "Concurrency")
                    self.assertEqual(
                        app.test_tree.heading("kv_usage")["text"], "KV usage")

                    details = app.calc_detail_text.get("1.0", "end-1c")
                    self.assertIn("Case 1", details)
                    self.assertIn("Concurrency (formula)", details)
                    self.assertIn("Minimum requests", details)
                    self.assertIn("KV usage", details)
                    self.assertNotIn("请求数", details)
                    self.assertNotIn("并发数", details)
                finally:
                    app.root.destroy()

    def test_docker_manager_logs_are_english(self):
        from docker_manager import DockerManager

        class FakeSSH:
            def file_exists(self, _path):
                return True

            def execute(self, _command):
                return 0, "", ""

        i18n.set_language("en")
        manager = DockerManager(FakeSSH())
        manager.remote_work_base = "/tmp/aisbench_deploy"
        messages = []
        self.assertTrue(manager.remove_work_dir(messages.append))
        text = "".join(messages)
        self.assertIn("Deleting temporary deployment directory: /tmp/aisbench_deploy", text)
        self.assertIn("Host temporary directory deleted", text)
        self.assertNotIn("删除临时部署目录", text)


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
                    app.current_step = 1
                    app.deployed = True
                    app.local_output_var.set("D:/results/run1")
                    app.results_tree.insert("", tk.END, values=(
                        "4,096", "1,024", "10,000", "100", "50",
                        "12.34", "56.78", "0.12", "0.03", "9.87",
                        "85.2", "12.3"))
                    app.results_info_lbl.config(
                        text="1 records  |  CSV: r.csv  |  Log: logs")
                    app.deploy_btn.config(text="Redeploy")

                    app.language_var.set("English")
                    app._on_language_change()

                    self.assertEqual(app.current_step, 1)
                    self.assertEqual(app.local_output_var.get(), "D:/results/run1")
                    first = app.results_tree.get_children()[0]
                    self.assertEqual(
                        app.results_tree.item(first)["values"][0], "4,096")
                    self.assertEqual(
                        app.results_info_lbl.cget("text"),
                        "1 records  |  CSV: r.csv  |  Log: logs")
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
