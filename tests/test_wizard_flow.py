import tkinter as tk
import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import i18n
import main
from docker_manager import DockerManager


class LanguageResetMixin:
    def _settings_patcher(self):
        import settings_manager
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "settings.json"
        return mock.patch.object(settings_manager, "settings_path",
                                  return_value=path)

    def setUp(self):
        super().setUp()
        i18n.set_language("zh")

    def tearDown(self):
        i18n.set_language("zh")


class WizardFlowTests(unittest.TestCase):
    def test_deploy_config_cases_execute_steps_are_merged_into_create_task(self):
        self.assertEqual(
            main.WizardApp.STEP_TITLES,
            ["SSH连接", "创建任务"],
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


class CreateTaskFlowTests(LanguageResetMixin, unittest.TestCase):
    """步骤2-5合并为"创建任务": 服务参数自动生成, config自动写入, 一键执行"""

    def _app(self):
        with self._settings_patcher():
            app = main.WizardApp()
        self.addCleanup(app.root.destroy)
        return app

    def test_primary_buttons_exist(self):
        app = self._app()
        self.assertEqual(app.create_task_btn.cget("text"), "🚀 创建任务")
        self.assertEqual(app.deploy_btn.cget("text"), "仅部署容器")

    def test_service_fields_are_hidden_by_default_and_expandable(self):
        app = self._app()
        app._show_step(1)
        app.root.update()

        self.assertFalse(app.service_advanced_var.get())
        self.assertFalse(app.service_advanced_frame.winfo_ismapped())

        app._toggle_service_advanced()
        app.root.update()
        self.assertTrue(app.service_advanced_var.get())
        self.assertTrue(app.service_advanced_frame.winfo_ismapped())
        self.assertEqual(app.service_toggle_btn.cget("text"), "收起 ▴")

        app._toggle_service_advanced()
        app.root.update()
        self.assertFalse(app.service_advanced_var.get())
        self.assertFalse(app.service_advanced_frame.winfo_ismapped())

    def test_build_config_dict_uses_automatic_service_defaults(self):
        app = self._app()
        app.conn_vars["host"].set("192.168.5.10")
        app.model_path_var.set("/mnt/models/ds")

        config = app._build_config_dict()

        self.assertEqual(config["model_name"], "ds")
        self.assertEqual(config["host_ip"], "192.168.5.10")
        self.assertEqual(config["host_port"], "8000")
        self.assertEqual(config["model_path"], "/mnt/models/ds")
        self.assertEqual(config["work_path"], "/benchmark")
        self.assertEqual(config["pod_info"], "")

        # 高级设置可覆盖默认值
        app.model_name_var.set("qwen")
        app.host_port_var.set("9000")
        config = app._build_config_dict()
        self.assertEqual(config["model_name"], "qwen")
        self.assertEqual(config["host_port"], "9000")

    def test_write_config_automatically_writes_and_verifies(self):
        from config_manager import ConfigManager

        app = self._app()
        app.conn_vars["host"].set("192.168.5.10")
        app.model_path_var.set("/mnt/models/ds")
        docker = mock.Mock()
        docker.code_mount_path = (
            "/benchmark/ais_bench/aisbench_auto_tools_prefix-main")
        app.docker = docker

        config_mgr = mock.Mock(wraps=ConfigManager(docker))
        content = config_mgr.generate_config_content(app._build_config_dict())
        config_mgr.read_config_from_container.return_value = content
        app.config_mgr = config_mgr

        self.assertTrue(app._write_config_automatically())
        config_mgr.write_config_to_container.assert_called_once()
        written = config_mgr.write_config_to_container.call_args.args[0]
        self.assertEqual(written["model_name"], "ds")
        self.assertEqual(written["host_ip"], "192.168.5.10")

        # 回读不一致时中止执行
        config_mgr.read_config_from_container.return_value = (
            content.replace('MODEL_PATH = "/mnt/models/ds"',
                            'MODEL_PATH = "/wrong/path"'))
        self.assertFalse(app._write_config_automatically())

    def test_prepare_and_run_tests_writes_config_first(self):
        app = self._app()

        with mock.patch.object(app, "_write_config_automatically",
                               return_value=False) as write_config:
            with mock.patch.object(app, "_run_test_sequence") as run:
                app._prepare_and_run_tests("D:/results")

        write_config.assert_called_once()
        run.assert_not_called()

    def test_create_task_warns_when_no_test_cases(self):
        app = self._app()
        app.ssh = mock.Mock()
        app.ssh.connected = True
        app.ssh.execute.return_value = (0, "", "")
        app.image_source_var.set("existing")
        app.remote_image_var.set("aisbench:v3.1")
        app.model_path_var.set("/mnt/models/ds")
        app.work_dir_var.set("/tmp/aisbench_deploy")
        app.local_output_var.set("D:/results")

        with mock.patch("main.showwarning") as warn:
            app._create_task()

        warn.assert_called_once()
        self.assertIn("请先生成测试用例", warn.call_args.args[1])

    def test_container_reusable_requires_running_and_same_model(self):
        app = self._app()
        docker = mock.Mock()
        docker.container_name = "aisbench-test-0101"
        docker.container_is_running.return_value = True
        app.docker = docker
        app.deployed = True
        app.deployed_model_path = "/mnt/models/ds"
        app.deployed_image = "aisbench:v3.1"
        app.remote_image_var.set("aisbench:v3.1")

        self.assertTrue(app._container_reusable("/mnt/models/ds"))

        # 模型路径变化后不能复用(挂载在创建容器时固定)
        self.assertFalse(app._container_reusable("/mnt/models/other"))
        # 容器停止后不能复用
        docker.container_is_running.return_value = False
        self.assertFalse(app._container_reusable("/mnt/models/ds"))

    def test_task_sequence_reuses_container_without_redeploy(self):
        app = self._app()
        docker = mock.Mock()
        docker.container_name = "aisbench-test-0101"
        app.docker = docker
        inputs = {
            "image_mode": "existing",
            "selected_image": "aisbench:v3.1",
            "tar": "",
            "model": "/mnt/models/ds",
            "work_dir": "/tmp/aisbench_deploy",
        }

        with mock.patch.object(app, "_write_config_automatically",
                               return_value=True) as write_config:
            with mock.patch.object(app, "_run_test_sequence") as run:
                app._task_sequence(inputs, "D:/results", reuse=True)

        write_config.assert_called_once()
        run.assert_called_once_with("D:/results")
        docker.stop_and_remove.assert_not_called()

    def test_task_sequence_deploys_when_not_reusable(self):
        app = self._app()
        app.docker = mock.Mock()
        app.docker.container_name = None
        inputs = {
            "image_mode": "existing",
            "selected_image": "aisbench:v3.1",
            "tar": "",
            "model": "/mnt/models/ds",
            "work_dir": "/tmp/aisbench_deploy",
        }

        with mock.patch.object(app, "_deploy_sequence", return_value=True) as deploy:
            with mock.patch.object(app, "_write_config_automatically",
                                   return_value=True) as write_config:
                with mock.patch.object(app, "_run_test_sequence") as run:
                    app._task_sequence(inputs, "D:/results", reuse=False)

        deploy.assert_called_once_with("/mnt/models/ds", "", "aisbench:v3.1")
        write_config.assert_called_once()
        run.assert_called_once_with("D:/results")

    def test_task_sequence_stops_when_deploy_fails(self):
        app = self._app()
        app.docker = mock.Mock()
        app.docker.container_name = None
        inputs = {
            "image_mode": "existing",
            "selected_image": "aisbench:v3.1",
            "tar": "",
            "model": "/mnt/models/ds",
            "work_dir": "/tmp/aisbench_deploy",
        }

        with mock.patch.object(app, "_deploy_sequence", return_value=False):
            with mock.patch.object(app, "_write_config_automatically") as write_config:
                with mock.patch.object(app, "_run_test_sequence") as run:
                    app._task_sequence(inputs, "D:/results", reuse=False)

        write_config.assert_not_called()
        run.assert_not_called()

    def test_collect_task_inputs_keeps_existing_docker_reference(self):
        app = self._app()
        app.ssh = mock.Mock()
        app.ssh.connected = True
        app.ssh.execute.return_value = (0, "", "")
        docker = mock.Mock()
        docker.container_name = "aisbench-test-0101"
        app.docker = docker
        app.image_source_var.set("existing")
        app.remote_image_var.set("aisbench:v3.1")
        app.model_path_var.set("/mnt/models/ds")
        app.work_dir_var.set("/tmp/aisbench_deploy")

        inputs = app._collect_task_inputs()

        self.assertIsNotNone(inputs)
        self.assertIs(app.docker, docker)
        self.assertEqual(app.docker.container_name, "aisbench-test-0101")

    def test_language_switch_preserves_code_source_and_case_lengths(self):
        app = self._app()
        app._show_step(1)
        app.code_source_var.set("zip")
        app.zip_path.set("D:/code/test.zip")
        app.input_length_vars[8192].set(True)
        app.input_length_vars[32768].set(True)
        app.input_length_vars[16384].set(False)
        app.output_length_vars[512].set(False)

        app.language_var.set("English")
        app._on_language_change()

        self.assertEqual(app.code_source_var.get(), "zip")
        self.assertEqual(app.zip_path.get(), "D:/code/test.zip")
        self.assertTrue(app.input_length_vars[8192].get())
        self.assertFalse(app.input_length_vars[16384].get())
        self.assertTrue(app.input_length_vars[32768].get())
        self.assertFalse(app.output_length_vars[512].get())


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

    def execute_with_callback(self, command, callback=None, timeout=300):
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
                deploy_ok = app._deploy_sequence(
                    "/mnt/models/ds", "", "aisbench:v3.1"
                )
                app._docker_log_handler.finalize()
                app.root.update()

            self.assertTrue(deploy_ok)
            self.assertEqual(app.deployed_model_path, "/mnt/models/ds")
            self.assertEqual(app.deployed_image, "aisbench:v3.1")

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


class RemoteImageFilterTests(LanguageResetMixin, unittest.TestCase):
    """执行机已有镜像支持关键字筛选, 便于在大量镜像中定位目标"""

    IMAGES = [
        {"name": "aisbench:v3.1", "id": "img1", "created": "1 day ago", "size": "12GB"},
        {"name": "registry.example.com/team/aisbench-runtime:vllm",
         "id": "img2", "created": "2 days ago", "size": "11GB"},
        {"name": "ubuntu:24.04", "id": "img3", "created": "3 days ago", "size": "100MB"},
    ]

    def _app_with_images(self):
        with self._settings_patcher():
            app = main.WizardApp()
        app.remote_images = [dict(item) for item in self.IMAGES]
        app._apply_remote_image_filter(update_selection=False)
        return app

    def test_filter_is_case_insensitive_substring_match(self):
        app = self._app_with_images()
        try:
            self.assertEqual(
                list(app.remote_image_combo.cget("values")),
                [item["name"] for item in self.IMAGES])

            app.remote_image_filter_var.set("AIS")

            self.assertEqual(
                list(app.remote_image_combo.cget("values")),
                ["aisbench:v3.1",
                 "registry.example.com/team/aisbench-runtime:vllm"])
            self.assertEqual(
                app.remote_image_filter_hint.cget("text"),
                "筛选: 2/3 个镜像")
        finally:
            app.root.destroy()

    def test_clearing_filter_restores_all_images(self):
        app = self._app_with_images()
        try:
            app.remote_image_filter_var.set("ubuntu")
            app.remote_image_filter_var.set("")

            self.assertEqual(
                list(app.remote_image_combo.cget("values")),
                [item["name"] for item in self.IMAGES])
            self.assertEqual(app.remote_image_filter_hint.cget("text"), "")
        finally:
            app.root.destroy()

    def test_filter_out_of_scope_selection(self):
        app = self._app_with_images()
        try:
            app.remote_image_var.set("ubuntu:24.04")

            app.remote_image_filter_var.set("aisbench")

            self.assertEqual(app.remote_image_var.get(), "")
        finally:
            app.root.destroy()

    def test_refresh_with_filter_reports_no_match_without_switching_to_upload(self):
        with self._settings_patcher():
            app = main.WizardApp()
        try:
            ssh = FakeDeploySSH()
            app.ssh = ssh
            app.docker = DockerManager(ssh)
            app.docker.list_images = lambda: [dict(item) for item in self.IMAGES]
            app.remote_image_filter_var.set("does-not-exist")

            app._refresh_remote_images()

            self.assertEqual(app.image_source_var.get(), "existing")
            self.assertEqual(app.remote_image_var.get(), "")
            self.assertEqual(
                list(app.remote_image_combo.cget("values")), [])
            self.assertIn("未找到匹配当前关键字的镜像",
                          app.image_list_status.cget("text"))
        finally:
            app.root.destroy()

    def test_language_switch_preserves_filter_keyword(self):
        app = self._app_with_images()
        try:
            app.remote_image_filter_var.set("aisbench")
            app.remote_image_var.set("aisbench:v3.1")

            app.language_var.set("English")
            app._on_language_change()

            self.assertEqual(app.remote_image_filter_var.get(), "aisbench")
            self.assertEqual(app.remote_image_var.get(), "aisbench:v3.1")
            self.assertEqual(
                list(app.remote_image_combo.cget("values")),
                ["aisbench:v3.1",
                 "registry.example.com/team/aisbench-runtime:vllm"])
            self.assertEqual(
                app.remote_image_filter_hint.cget("text"),
                "Filtered: 2/3 image(s)")
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
