import tkinter as tk
import json
from tkinter import scrolledtext
import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import main
from docker_manager import DockerManager


class WizardFlowTests(unittest.TestCase):
    def test_docker_and_file_steps_are_merged(self):
        self.assertEqual(
            main.WizardApp.STEP_TITLES,
            ["SSH连接", "Docker部署", "配置文件", "测试用例", "执行测试"],
        )

    def test_residual_container_cleanup_is_supported(self):
        self.assertTrue(hasattr(main.WizardApp, "_open_residual_container_dialog"))
        self.assertTrue(hasattr(main.WizardApp, "_start_residual_scan"))

    def test_container_workspace_is_not_host_mounted(self):
        import inspect

        signature = inspect.signature(main.DockerManager.create_container)
        self.assertNotIn("code_host_path", signature.parameters)
        self.assertIn("org.aisbench-prefix-tools.managed=true",
                      main.DockerManager.MANAGED_LABEL)


class DockerDeployFormTests(unittest.TestCase):
    """步骤2只填写镜像来源和模型路径; 其余服务参数在步骤3填写"""

    @classmethod
    def setUpClass(cls):
        # 共用一个App实例, 减少Tk root创建/销毁次数(Windows下频繁重建易抖动)
        cls._tmp = tempfile.TemporaryDirectory()
        cls._patcher = mock.patch(
            "settings_manager.settings_path",
            return_value=Path(cls._tmp.name) / "settings.json")
        cls._patcher.start()
        cls.app = main.WizardApp()

    @classmethod
    def tearDownClass(cls):
        cls.app.root.destroy()
        cls._patcher.stop()
        cls._tmp.cleanup()

    def _collect_labels(self, widget):
        out = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                out.append(child)
            out.extend(self._collect_labels(child))
        return out

    def _collect_labels(self, widget):
        out = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                out.append(child)
            out.extend(self._collect_labels(child))
        return out

    def test_model_service_fields_moved_to_config_step(self):
        app = self.app

        # 步骤2不再持有模型名称/vLLM IP/端口输入
        for attr in ("model_name_var", "host_ip_var", "host_port_var",
                     "api_key_var"):
            self.assertFalse(hasattr(app, attr), attr)

        step2_texts = [lbl.cget("text") for lbl in
                       self._collect_labels(app.step_frames[1])]
        for text in ("模型名称 (--served-model-name):", "vLLM服务 IP:",
                     "vLLM服务端口:"):
            self.assertNotIn(text, step2_texts)

        # 步骤3填写且默认留空, 作为必填项
        for key in ("model_name", "host_ip", "host_port"):
            self.assertIn(key, app.config_entry_vars)
            self.assertEqual(app.config_entry_vars[key].get(), "")

    def test_required_fields_are_marked_with_red_star(self):
        app = self.app

        def _star_labels(frame):
            return [lbl for lbl in self._collect_labels(frame)
                    if str(lbl.cget("text")) == "*"
                    and str(lbl.cget("fg")) == main.COLOR_ERROR]

        # 步骤2: 镜像来源 + 模型路径
        self.assertEqual(len(_star_labels(app.step_frames[1])), 2)
        # 步骤1: 执行机IP + 用户名
        self.assertEqual(len(_star_labels(app.step_frames[0])), 2)
        # 步骤3: MODEL_NAME/MODEL_PATH/HOST_IP/HOST_PORT
        # POD_INFO为PD分离下多DP场景必填, 不用红色*星号标记
        self.assertEqual(len(_star_labels(app.step_frames[2])), 4)
        pod_labels = [lbl for lbl in
                      self._collect_labels(app.step_frames[2])
                      if "POD_INFO" in str(lbl.cget("text"))]
        self.assertTrue(pod_labels)
        self.assertIn("PD分离下多DP场景必填", pod_labels[0].cget("text"))

    def test_remote_images_support_keyword_filter(self):
        app = self.app
        app.image_filter_var.set("")
        app.remote_images = [
            {"name": "aisbench:v3.1", "id": "aaa", "created": "1d",
             "size": "10GB"},
            {"name": "registry.example.com/benchmark-runtime:20261013",
             "id": "bbb", "created": "2d", "size": "12GB"},
            {"name": "nginx:latest", "id": "ccc", "created": "3d",
             "size": "100MB"},
        ]
        app._apply_image_filter()
        self.assertEqual(
            list(app.remote_image_combo.cget("values")),
            ["aisbench:v3.1",
             "registry.example.com/benchmark-runtime:20261013",
             "nginx:latest"])

        app.image_filter_var.set("benchmark")
        app._on_image_filter_changed()
        self.assertEqual(
            list(app.remote_image_combo.cget("values")),
            ["registry.example.com/benchmark-runtime:20261013"])
        self.assertIn("3", app.image_list_status.cget("text"))

        app.image_filter_var.set("AISBENCH")
        app._on_image_filter_changed()
        self.assertEqual(list(app.remote_image_combo.cget("values")),
                         ["aisbench:v3.1"])

        app._clear_image_filter()
        self.assertEqual(len(app.remote_image_combo.cget("values")), 3)

    def test_pod_info_help_tooltip_matches_config_comment(self):
        app = self.app

        self.assertTrue(hasattr(app, "pod_info_tooltip"))
        self.assertIn("PD分离场景请填写各个P节点的IP和对应dp域的port",
                      app.pod_info_tooltip.text)

        from config_manager import ConfigManager
        manager = ConfigManager(docker=None)
        content = manager.generate_config_content({
            "model_name": "ds", "model_path": "/mnt/models/ds",
            "host_ip": "10.0.0.1", "host_port": "8000",
            "dataset_path": "/benchmark/ais_bench/"
                            "aisbench_auto_tools_prefix-main",
        })
        self.assertIn("# 各节点信息，格式为 [\"{ip}:{port}\"]", content)
        self.assertIn("# 用于查询vllm metrics计算各个dp域的prefix cache命中率，"
                      "不配置默认为HOST_IP:HOST_PORT", content)
        self.assertIn("# PD分离场景请填写各个P节点的IP和对应dp域的port", content)
        self.assertIn(
            "# POD_INFO = [\"141.xx.xx.11:8000\",\"141.xx.xx.12:8000\"]",
            content)

    def test_language_rebuild_keeps_keyword_filter_and_translates_labels(self):
        import i18n
        app = self.app
        app.remote_images = [
            {"name": "aisbench:v3.1", "id": "aaa", "created": "1d",
             "size": "10GB"},
            {"name": "registry.example.com/benchmark-runtime:20261013",
             "id": "bbb", "created": "2d", "size": "12GB"},
        ]
        app.image_filter_var.set("benchmark")
        app._apply_image_filter()

        app.language_var.set("English")
        app._on_language_change()
        self.addCleanup(i18n.set_language, "zh")

        # 重建后保留筛选结果与关键词
        self.assertEqual(app.image_filter_var.get(), "benchmark")
        self.assertEqual(
            list(app.remote_image_combo.cget("values")),
            ["registry.example.com/benchmark-runtime:20261013"])

        step2_texts = [lbl.cget("text") for lbl in
                       self._collect_labels(app.step_frames[1])]
        self.assertIn("Keyword filter:", step2_texts)
        step3_texts = [lbl.cget("text") for lbl in
                       self._collect_labels(app.step_frames[2])]
        for text in ("MODEL_NAME (model name)",
                     "HOST_IP (vLLM service IP)",
                     "HOST_PORT (vLLM service port)",
                     "POD_INFO (required for multi-DP under PD disaggregation)"):
            self.assertIn(text, step3_texts)

        # 切回中文, 避免影响类内其他断言
        app.language_var.set("中文")
        app._on_language_change()


class FakeDeploySSH:
    """模拟执行机: 记录命令并模拟docker/文件系统行为"""

    connected = True

    class _SFTP:
        @staticmethod
        def get(remote, local):
            with open(local, "wb") as f:
                f.write(b"fake")

    sftp = _SFTP()

    def __init__(self):
        self.commands = []
        self.dirs = set()

    def execute(self, command, timeout=300):
        self.commands.append(command)
        if command.startswith("docker --version"):
            return 0, "Docker version 27.3.1", ""
        if command.startswith("docker ps -a --filter"):
            return 0, "", ""
        if command.startswith("docker ps --filter"):
            return 0, "Up 2 seconds", ""
        if "docker images" in command:
            return 0, "aisbench:v3.1", ""
        if command.startswith("docker exec"):
            if " ls " in command:
                return 0, "run.py\nconfig.py", ""
            if " test -d " in command or " test -e " in command:
                return 0, "", ""
            return 0, "", ""
        if command.startswith("rm -rf "):
            self.dirs.discard(command[len("rm -rf "):])
            return 0, "", ""
        if command.startswith("mkdir -p "):
            self.dirs.add(command[len("mkdir -p "):])
            return 0, "", ""
        if command.startswith("ls "):
            return 0, "", ""
        return 0, "", ""

    def execute_with_callback(self, command, callback=None, timeout=300,
                              stop_event=None):
        self.commands.append(command)
        if callback:
            callback("ok\n")
        return 0

    def mkdir_p(self, path):
        self.dirs.add(path)
        self.commands.append(f"mkdir -p {path}")

    def file_exists(self, path):
        return path in self.dirs

    def upload_file(self, local_path, remote_path, progress=None):
        return True


class LiveLogAbnormalTests(unittest.TestCase):
    """执行日志的WARN/ERROR行需要单独提示并可跳转回总日志"""

    def test_abnormal_lines_are_collected_and_tagged(self):
        root = tk.Tk()
        text = scrolledtext.ScrolledText(root)
        entries = []
        try:
            handler = main.LiveLogHandler(
                text,
                abnormal_callback=lambda kind, line, msg: entries.append(
                    (kind, line, msg)))
            handler.append("normal line\nWARNING: model warming up\n")
            handler.append("ERROR: request failed\n")
            handler.flush()
            handler.finalize()

            self.assertEqual(
                entries,
                [("warning", 2, "WARNING: model warming up"),
                 ("error", 3, "ERROR: request failed")])
            self.assertIn("log_warning", text.tag_names("2.0"))
            self.assertIn("log_error", text.tag_names("3.0"))
        finally:
            root.destroy()


class DeploySequenceTests(unittest.TestCase):
    def test_deploy_imports_code_into_container_and_removes_staging_dir(self):
        app = main.WizardApp()
        try:
            ssh = FakeDeploySSH()
            app.ssh = ssh
            app.docker = DockerManager(ssh)
            app.image_source_var.set("existing")
            app.remote_image_var.set("aisbench:v3.1")
            app.code_source_var.set("builtin")
            app.model_path_var.set("/mnt/models/ds")
            app.work_dir_var.set("/tmp/AISBench_Prefix_Tools")

            with mock.patch("main.showinfo"):
                app._deploy_sequence(
                    "/mnt/models/ds", "", "aisbench:v3.1"
                )
                app._docker_log_handler.finalize()
                app.root.update()

            run_cmd = next(
                c for c in ssh.commands if c.startswith("docker run"))
            self.assertIn("--label org.aisbench-prefix-tools.managed=true", run_cmd)
            self.assertNotIn("aisbench_auto_tools_prefix-main", run_cmd)

            cp_cmd = next(
                c for c in ssh.commands if c.startswith("docker cp"))
            self.assertIn("docker cp /tmp/AISBench_Prefix_Tools/"
                          "aisbench_auto_tools_prefix-main/.", cp_cmd)
            self.assertIn(":/benchmark/ais_bench/"
                          "aisbench_auto_tools_prefix-main", cp_cmd)

            self.assertIn("rm -rf /tmp/AISBench_Prefix_Tools", ssh.commands)
            self.assertNotIn("/tmp/AISBench_Prefix_Tools", ssh.dirs)
            self.assertTrue(app.docker.container_name.startswith("aisbench-test-"))
            self.assertIsNotNone(app.config_mgr)
            # 部署完成: 容器内写入测试状态标记(初始化)
            state_cmd = next(
                c for c in ssh.commands if ".aisbench_test_state" in c)
            self.assertIn("docker exec", state_cmd)
            self.assertIn("initialized", state_cmd)
        finally:
            app.root.destroy()


class TestExecutionStateTests(unittest.TestCase):
    """容器内测试状态标记应随测试执行阶段更新"""

    def _build_app(self, tmp):
        settings_file = Path(tmp) / "settings.json"
        patcher = mock.patch(
            "settings_manager.settings_path", return_value=settings_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = main.WizardApp()
        self.addCleanup(app.root.destroy)

        app.designer.set_kv_cache_info(1_000_000, 2, 8192)
        app.designer.set_input_lengths([4096])
        app.designer.set_output_lengths([1024])
        app.designer.set_repeat_rate(0.8)
        app.designer.set_request_rate(0)
        app.designer.generate_test_cases()

        calls = []
        docker = mock.Mock()
        docker.code_mount_path = (
            "/benchmark/ais_bench/aisbench_auto_tools_prefix-main")
        docker.container_name = "aisbench-test-unit"
        docker.TEST_STATE_INITIALIZED = DockerManager.TEST_STATE_INITIALIZED
        docker.TEST_STATE_RUNNING = DockerManager.TEST_STATE_RUNNING
        docker.TEST_STATE_COMPLETED = DockerManager.TEST_STATE_COMPLETED
        docker.TEST_STATE_ABNORMAL = DockerManager.TEST_STATE_ABNORMAL
        docker.write_script.side_effect = (
            lambda *a, **k:
            "/benchmark/ais_bench/aisbench_auto_tools_prefix-main/run_tests.sh")
        docker.set_test_state.side_effect = (
            lambda state, *a, **k: calls.append(state) or True)
        docker.find_latest_log_dir.return_value = (
            "/benchmark/ais_bench/aisbench_auto_tools_prefix-main/test_logs_x")
        docker.download_logs.return_value = ["/fake/test_1.log"]
        docker.download_extra_files.return_value = []
        app.docker = docker
        return app, docker, calls

    def _run(self, app, tmp):
        with mock.patch.object(app, "_check_model_path_in_container",
                               return_value=(True, "OK")):
            with mock.patch("main.parse_log_directory", return_value=[]):
                app._run_test_sequence(os.path.join(tmp, "results"))

    def test_run_sequence_marks_running_then_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, docker, calls = self._build_app(tmp)
            docker.run_script.return_value = 0
            self._run(app, tmp)
            self.assertEqual(calls, ["running", "completed"])

    def test_run_sequence_marks_abnormal_when_script_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, docker, calls = self._build_app(tmp)
            docker.run_script.return_value = 1
            self._run(app, tmp)
            self.assertEqual(calls, ["running", "abnormal"])

    def test_run_sequence_marks_abnormal_when_script_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, docker, calls = self._build_app(tmp)
            docker.write_script.side_effect = lambda *a, **k: ""
            self._run(app, tmp)
            self.assertEqual(calls, ["abnormal"])

    def test_run_sequence_stops_and_marks_abnormal_after_user_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, docker, calls = self._build_app(tmp)

            def cancel_during_script(*args, **kwargs):
                app._test_cancel_event.set()
                return -1

            docker.run_script.side_effect = cancel_during_script
            self._run(app, tmp)

            self.assertEqual(calls, ["running", "abnormal"])
            docker.download_logs.assert_not_called()

    def test_abnormal_panel_click_jumps_to_log_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, _, _ = self._build_app(tmp)
            app.exec_log.insert("1.0", "first\nERROR: request failed\n")
            app._add_exec_abnormal_entry("error", 2, "ERROR: request failed")
            app.exec_abnormal_tree.selection_set("0")
            app._jump_to_exec_abnormal_log()

            ranges = app.exec_log.tag_ranges("log_highlight")
            self.assertEqual((str(ranges[0]), str(ranges[1])),
                             ("2.0", str(app.exec_log.index("2.end"))))

    def test_run_sequence_prefixes_result_dir_with_task_name_and_saves_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, docker, _ = self._build_app(tmp)
            docker.run_script.return_value = 0
            results_root = os.path.join(tmp, "results")

            with mock.patch.object(app, "_check_model_path_in_container",
                                   return_value=(True, "OK")):
                with mock.patch("main.parse_log_directory", return_value=[]):
                    app._run_test_sequence(results_root, "夜间基线")

            result_dirs = os.listdir(results_root)
            self.assertEqual(len(result_dirs), 1)
            self.assertRegex(result_dirs[0], r"^夜间基线_test_logs_\d{8}_\d{6}$")

            with open(os.path.join(results_root, result_dirs[0], "task_info.json"),
                      encoding="utf-8") as f:
                info = json.load(f)
            self.assertEqual(info["task_name"], "夜间基线")
            self.assertEqual(info["status"], "no_results")
            self.assertEqual(info["container_name"], "aisbench-test-unit")
            self.assertEqual(info["result_dir_name"], result_dirs[0])

    def test_sanitize_task_name_replaces_unsafe_characters(self):
        self.assertEqual(
            main.sanitize_task_name("my:task?/name"),
            "my_task__name")
        self.assertEqual(main.sanitize_task_name("  ..task..  "), "task")
        self.assertEqual(main.sanitize_task_name(""), "")
        self.assertEqual(len(main.sanitize_task_name("x" * 100)), 80)

    def test_result_directory_open_button_is_enabled_and_opens_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, _, _ = self._build_app(tmp)
            self.assertEqual(str(app.open_result_btn.cget("state")), "disabled")

            app._set_result_directory(tmp)
            self.assertEqual(str(app.open_result_btn.cget("state")), "normal")

            with mock.patch.object(main.os, "startfile", create=True) as startfile:
                app._open_result_directory()
                startfile.assert_called_once_with(tmp)


class FormLayoutTests(unittest.TestCase):
    """Long values must not push controls outside the window."""

    LONG = ("registry.example.com/team/aisbench-benchmark-runtime-cuda12.4"
            "-vllm0.9.2:20261013-release")

    def _collect(self, widget, cls):
        out = []
        for child in widget.winfo_children():
            if isinstance(child, cls):
                out.append(child)
            out.extend(self._collect(child, cls))
        return out

    def test_long_values_do_not_push_buttons_outside_window(self):
        app = main.WizardApp()
        try:
            app.current_step = 1
            app._show_step(1)
            app.root.geometry("900x620")   # minimum supported window width
            app.root.update()
            app.root.update_idletasks()

            app.image_source_var.set("upload")
            app._on_image_source_change()
            app.code_source_var.set("zip")
            app._on_code_source_change()
            app.tar_path.set("D:/" + self.LONG + ".tar.gz")
            app.zip_path.set("D:/" + self.LONG + ".zip")
            app.model_path_var.set("/mnt/models/" + self.LONG)
            app.work_dir_var.set("/tmp/" + self.LONG)
            app.root.update()
            app.root.update_idletasks()

            win_right = app.root.winfo_rootx() + app.root.winfo_width()
            self.assertEqual(app.root.winfo_width(), 900)

            for btn in self._collect(app.step_frames[1], tk.Button):
                if not btn.winfo_ismapped():
                    continue
                right = btn.winfo_rootx() + btn.winfo_width()
                self.assertLessEqual(
                    right, win_right + 1,
                    f"button {btn.cget('text')!r} overflows: "
                    f"right={right}, window right={win_right}")

            entry = next(c for c in app.tar_upload_frame.winfo_children()
                         if isinstance(c, tk.Entry))
            self.assertGreater(
                entry.winfo_width(), 150,
                "input field collapsed instead of expanding")
        finally:
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
