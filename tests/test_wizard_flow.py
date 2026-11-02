"""向导流程测试: 三页导航 / 创建任务表单 / 任务列表 / 确认对话框 / 布局"""

import os
import tempfile
import tkinter as tk
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import i18n
import main
from task_manager import TaskInputs, TaskManager, TaskStatus


class LanguageResetMixin:
    """隔离本地settings.json并重置语言"""

    def _settings_patcher(self):
        import settings_manager
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "settings.json"
        return mock.patch.object(settings_manager, "settings_path",
                                  return_value=path)

    def _task_manager_patcher(self):
        """TaskManager替换为轻量mock, 不读写真实app数据目录"""
        tm = mock.Mock(spec=TaskManager)
        tm.tasks = {}
        tm.all_tasks.return_value = []
        tm.active_tasks.return_value = []
        tm.tasks_with_containers.return_value = []
        tm.get.return_value = None
        tm.copy_inputs.return_value = None
        tm.on_change = None
        return mock.patch.object(main, "TaskManager", return_value=tm), tm

    def setUp(self):
        super().setUp()
        i18n.set_language("zh")

    def tearDown(self):
        i18n.set_language("zh")


class AppMixin(LanguageResetMixin):
    def _app(self):
        with self._settings_patcher():
            with self._task_manager_patcher()[0]:
                app = main.WizardApp()
        self.addCleanup(app.root.destroy)
        return app


class WizardFlowTests(AppMixin, unittest.TestCase):
    def test_three_page_navigation_with_tasklist_always_accessible(self):
        self.assertEqual(
            main.WizardApp.STEP_TITLES,
            ["SSH连接", "创建任务", "任务列表"],
        )
        app = self._app()
        self.assertEqual(len(app.step_frames), 3)
        # 未连接时也可直接进入任务列表
        app._show_step(2)
        app.root.update()
        self.assertTrue(app.step_frames[2].winfo_ismapped())
        self.assertGreaterEqual(app._max_reached_step(), 2)

    def test_residual_container_cleanup_is_supported(self):
        self.assertTrue(hasattr(main.WizardApp, "_open_residual_container_dialog"))
        self.assertTrue(hasattr(main.WizardApp, "_start_residual_scan"))

    def test_container_workspace_is_not_host_mounted(self):
        import inspect
        signature = inspect.signature(main.DockerManager.create_container)
        self.assertNotIn("code_host_path", signature.parameters)
        self.assertIn("org.aisbench-prefix-tools.managed=true",
                      main.DockerManager.MANAGED_LABEL)


class CreateTaskFlowTests(AppMixin, unittest.TestCase):
    """创建任务页: 服务参数独立分区紧凑展示, 输入收集与确认执行"""

    def _fill_valid_form(self, app):
        app.ssh = mock.Mock()
        app.ssh.connected = True
        app.conn_vars["host"].set("192.168.1.30")
        app.image_source_var.set("existing")
        app.remote_image_var.set("aisbench:v3.1")
        app.model_path_var.set("/mnt/models/ds")
        app.work_dir_var.set("/tmp/AISBench_Prefix_Tools")
        app.kv_cache_var.set("1000000")
        app.dp_var.set("2")
        app.max_req_len_var.set("32768")
        app.local_output_var.set(os.path.join(tempfile.gettempdir(), "results"))
        # 生成用例
        app.designer.set_kv_cache_info(1_000_000, 2, 32768)
        app.designer.set_input_lengths([8192])
        app.designer.set_output_lengths([512])
        app.designer.generate_test_cases()

    def test_primary_buttons_exist(self):
        app = self._app()
        self.assertEqual(app.create_task_btn.cget("text"), "🚀 创建任务")
        self.assertEqual(app.preview_task_btn.cget("text"), "预览任务信息")

    def test_service_section_is_compact_and_always_visible(self):
        app = self._app()
        app._show_step(1)
        app.root.update()
        self.assertTrue(hasattr(app, "service_section_header"))
        for var in (app.model_name_var, app.host_ip_var, app.host_port_var,
                    app.api_key_var, app.pod_info_var):
            self.assertIsInstance(var, tk.StringVar)

    def test_collect_task_inputs_returns_snapshot_without_dialog(self):
        app = self._app()
        self._fill_valid_form(app)
        with mock.patch("main.showwarning") as warn:
            inputs, issues = app._collect_task_inputs(silent=True)
        warn.assert_not_called()
        self.assertEqual(issues, [])
        self.assertIsInstance(inputs, TaskInputs)
        self.assertEqual(inputs.model_path, "/mnt/models/ds")
        self.assertEqual(inputs.model_name, "ds")
        self.assertEqual(inputs.host_ip, "192.168.1.30")
        self.assertEqual(inputs.host_port, "8000")
        self.assertEqual(inputs.work_dir_base, "/tmp/AISBench_Prefix_Tools")
        self.assertEqual(len(inputs.cases), 1)

    def test_collect_task_inputs_reports_issues_silently(self):
        app = self._app()
        inputs, issues = app._collect_task_inputs(silent=True)
        # silent模式始终返回当前表单快照(供预览展示), 问题通过issues传递
        self.assertIsInstance(inputs, TaskInputs)
        self.assertTrue(issues)
        joined = "\n".join(issues)
        self.assertIn("模型", joined)
        self.assertIn("镜像", joined)
        self.assertIn("测试用例", joined)

    def test_task_name_defaults_to_service_and_time(self):
        app = self._app()
        self._fill_valid_form(app)
        inputs, _ = app._collect_task_inputs(silent=True)
        self.assertTrue(inputs.resolved_name().startswith("ds_"))
        app.task_name_var.set("my-benchmark")
        inputs2, _ = app._collect_task_inputs(silent=True)
        self.assertEqual(inputs2.resolved_name(), "my-benchmark")

    def test_create_task_requires_confirmation_dialog(self):
        app = self._app()
        self._fill_valid_form(app)
        with mock.patch.object(app, "_show_task_info_dialog") as show_dialog:
            app._create_task()
        show_dialog.assert_called_once_with(execute=True)
        app.task_manager.create_task.assert_not_called()

    def test_start_task_execution_creates_and_jumps_to_tasklist(self):
        app = self._app()
        self._fill_valid_form(app)
        inputs, _issues = app._collect_task_inputs(silent=True)
        fake_task = mock.Mock()
        fake_task.id = "t1"
        fake_task.display_name = "ds_x"
        fake_task.results = []
        fake_task.log_buffer = mock.Mock()
        fake_task.log_buffer.poll.return_value = ([], "")
        app.task_manager.create_task.return_value = fake_task
        app.task_manager.start_task.return_value = True
        app.task_manager.get.return_value = fake_task
        app.task_manager.all_tasks.return_value = [fake_task]

        app._start_task_execution(inputs)

        app.task_manager.create_task.assert_called_once()
        app.task_manager.start_task.assert_called_once_with("t1")
        self.assertEqual(app.current_step, 2)
        self.assertEqual(app.selected_task_id, "t1")

    def test_request_rate_validation(self):
        app = self._app()
        app.request_rate_var.set("0.3")
        ok, value = app._validate_request_rate()
        self.assertTrue(ok)
        self.assertEqual(value, 0.3)
        app.request_rate_var.set("abc")
        ok, value = app._validate_request_rate()
        self.assertFalse(ok)


class TaskListPageTests(AppMixin, unittest.TestCase):
    """任务列表页签: 表格 / 操作按钮 / 日志视图 / 操作行为"""

    def _task(self, **kw):
        task = mock.Mock()
        task.id = kw.get("id", "t1")
        task.display_name = kw.get("name", "task-1")
        task.status = kw.get("status", TaskStatus.COMPLETED)
        task.status_label.return_value = "已完成"
        task.created_at = datetime(2026, 11, 2, 12, 0, 0)
        task.finished_at = None
        task.image_name = "aisbench:v3.1"
        task.inputs = mock.Mock(
            selected_image="aisbench:v3.1", tar_path="", model_path="/m")
        task.container_name = "aisbench-test-x"
        task.deploy_work_dir = "/tmp/x"
        task.csv_path = "results.csv"
        task.result_dir = "D:/r"
        task.results = []
        task.resources_cleaned = False
        task.log_buffer = mock.Mock()
        task.log_buffer.poll.return_value = ([], "")
        return task

    def test_tasklist_page_widgets_exist(self):
        app = self._app()
        self.assertTrue(hasattr(app, "task_tree"))
        self.assertTrue(hasattr(app, "task_log_text"))
        self.assertTrue(hasattr(app, "task_result_tree"))
        self.assertEqual(app.task_cancel_btn.cget("text"), "取消任务")
        self.assertEqual(app.task_cleanup_btn.cget("text"), "清理资源")
        self.assertEqual(app.task_delete_btn.cget("text"), "删除数据")

    def test_select_task_shows_log_title_and_updates_actions(self):
        app = self._app()
        task = self._task()
        app.task_manager.get.return_value = task
        app.task_manager.all_tasks.return_value = [task]
        app._refresh_task_table()
        app._select_task("t1", reset_log=True)
        self.assertEqual(app.selected_task_id, "t1")
        self.assertIn("task-1", app.task_log_title_lbl.cget("text"))
        self.assertEqual(str(app.task_cancel_btn.cget("state")), "disabled")
        self.assertEqual(str(app.task_cleanup_btn.cget("state")), "normal")
        self.assertEqual(str(app.task_delete_btn.cget("state")), "normal")

    def test_cancel_selected_task_confirms_then_calls_manager(self):
        app = self._app()
        task = self._task(status=TaskStatus.RUNNING)
        app.task_manager.get.return_value = task
        app.selected_task_id = "t1"
        app.task_manager.cancel_task.return_value = True
        with mock.patch("main.askyesno", return_value=True):
            app._cancel_selected_task()
        app.task_manager.cancel_task.assert_called_once_with("t1")

    def test_copy_task_prefills_create_form(self):
        app = self._app()
        inputs = TaskInputs(
            name="copied", image_mode="existing",
            selected_image="aisbench:v3.1", model_path="/mnt/m",
            kv_cache="1000000", dp="2", max_req_len="32768",
            input_lengths=[8192], output_lengths=[512],
            cases=[{"input_len": 8192, "output_len": 512,
                    "data_num_recommended": 10, "data_num_min": 5,
                    "concurrency_recommended": 4, "concurrency_max": 8,
                    "prefix_num": 10, "repeat_rate": 0.9, "dp": 2,
                    "is_custom": False}])
        app.task_manager.copy_inputs.return_value = inputs
        app.task_manager.get.return_value = self._fake_task()
        app.selected_task_id = "t1"
        with mock.patch.object(app, "_show_step"):
            app._copy_selected_task()
        self.assertEqual(app.task_name_var.get(), "copied")
        self.assertEqual(app.model_path_var.get(), "/mnt/m")
        self.assertEqual(app.kv_cache_var.get(), "1000000")
        self.assertTrue(app.input_length_vars[8192].get())
        self.assertEqual(len(app.designer.test_cases), 1)

    def _fake_task(self):
        task = mock.Mock()
        task.id = "t1"
        task.display_name = "task-1"
        return task

    def test_delete_task_clears_view(self):
        app = self._app()
        task = self._task()
        app.task_manager.get.return_value = task
        app.selected_task_id = "t1"
        app.task_manager.delete_task.return_value = True
        with mock.patch("main.askyesnocancel", return_value=True):
            app._delete_selected_task()
        app.task_manager.delete_task.assert_called_once_with(
            "t1", delete_files=True)
        self.assertIsNone(app.selected_task_id)

    def test_poll_tasks_updates_table_and_selected_log(self):
        app = self._app()
        task = self._task()
        app.task_manager.tasks = {"t1": task}
        app.task_manager.all_tasks.return_value = [task]
        app.task_manager.get.return_value = task
        app.selected_task_id = "t1"
        task.log_buffer.poll.return_value = (["line1", "line2"], "pending...")
        app._poll_tasks()
        content = app.task_log_text.get("1.0", "end-1c")
        self.assertIn("line1", content)
        self.assertIn("line2", content)
        self.assertIn("pending...", content)
        task.log_buffer.poll.return_value = ([], "")
        app._poll_tasks()
        # 再次poll无新增时不重复追加
        task.log_buffer.reset_shown.assert_not_called()

    def test_update_task_results_view_renders_rows(self):
        app = self._app()
        task = self._task()
        task.results = [{
            "input_len": 8192, "output_len": 512, "total_req": 10,
            "max_cc": 100, "cc": 50, "input_token_throughput": "1",
            "output_throughput": "2", "TTFT_avg": "3", "TPOT_avg": "4",
            "qps": "5", "hbm_hit_rate": "6", "external_hit_rate": "7"}]
        app.task_manager.get.return_value = task
        app.selected_task_id = "t1"
        app._update_task_results_view()
        self.assertEqual(len(app.task_result_tree.get_children()), 1)


class MenuBarTests(AppMixin, unittest.TestCase):
    def test_menu_bar_has_help_and_about(self):
        app = self._app()
        self.assertTrue(callable(app._show_usage_help))
        self.assertTrue(callable(app._show_about))

    def test_about_dialog_opens(self):
        app = self._app()
        app._show_about()
        dialogs = [w for w in app.root.winfo_children()
                   if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(dialogs), 1)
        self.assertIn("AISBench", dialogs[0].title())
        dialogs[0].destroy()


class ExitCheckTests(AppMixin, unittest.TestCase):
    def test_exit_allowed_when_no_active_tasks_or_containers(self):
        app = self._app()
        self.assertTrue(app._exit_check_cleanup())

    def test_exit_prompts_when_task_active(self):
        app = self._app()
        task = self._task() if hasattr(self, "_task") else mock.Mock()
        task.display_name = "running-task"
        app.task_manager.active_tasks.return_value = [task]
        with mock.patch("main.askyesno", return_value=False) as ask:
            self.assertFalse(app._exit_check_cleanup())
        ask.assert_called_once()

    def test_exit_prompts_cleanup_when_containers_remain(self):
        app = self._app()
        task = mock.Mock()
        task.container_name = "aisbench-test-x"
        task.deploy_work_dir = ""
        app.task_manager.active_tasks.return_value = []
        app.task_manager.tasks_with_containers.return_value = [task]
        with mock.patch("main.askyesnocancel", return_value=None) as ask:
            self.assertFalse(app._exit_check_cleanup())
        ask.assert_called_once()


class WorkDirBrowseTests(AppMixin, unittest.TestCase):
    def test_browse_work_dir_uses_remote_dir_browser(self):
        app = self._app()
        app.ssh = mock.Mock()
        app.ssh.connected = True
        with mock.patch.object(app, "_open_remote_dir_browser") as browse:
            app._browse_remote_work_dir()
        browse.assert_called_once()
        args = browse.call_args.args
        self.assertIn("临时部署目录", args[0])

    def test_work_dir_default_kept(self):
        app = self._app()
        self.assertEqual(app.work_dir_var.get(), "/tmp/AISBench_Prefix_Tools")


class LanguageStateTests(AppMixin, unittest.TestCase):
    def test_language_switch_preserves_form_values_and_step(self):
        app = self._app()
        app.task_name_var.set("my-task")
        app.model_path_var.set("/mnt/models/ds")
        app.kv_cache_var.set("1000000")
        app._show_step(1)

        app.language_var.set("English")
        app._on_language_change()

        self.assertEqual(i18n.get_language(), "en")
        self.assertEqual(app.task_name_var.get(), "my-task")
        self.assertEqual(app.model_path_var.get(), "/mnt/models/ds")
        self.assertEqual(app.kv_cache_var.get(), "1000000")
        self.assertEqual(app.current_step, 1)


class MouseWheelTests(AppMixin, unittest.TestCase):
    def test_high_precision_small_delta_does_not_raise(self):
        app = self._app()
        app._show_step(1)
        app.root.update()
        event = mock.Mock()
        event.delta = 40  # 高精度滚轮/触控板: 小于120
        event.x_root = app._content_canvas.winfo_rootx()
        event.y_root = app._content_canvas.winfo_rooty()
        event.widget = app._content_canvas
        with mock.patch.object(
                app.root, "winfo_containing",
                return_value=app.step_frames[1]):
            app._on_mousewheel(event)  # 不应抛异常


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
        import settings_manager
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings_file = Path(tmp.name) / "settings.json"
        tm = mock.Mock(spec=TaskManager)
        tm.tasks = {}
        tm.all_tasks.return_value = []
        tm.active_tasks.return_value = []
        tm.tasks_with_containers.return_value = []
        tm.get.return_value = None
        with mock.patch.object(settings_manager, "settings_path",
                                return_value=settings_file):
            with mock.patch.object(main, "TaskManager", return_value=tm):
                app = main.WizardApp()
        try:
            app._show_step(1)
            app.root.geometry("960x640")
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
            app.task_name_var.set(self.LONG)
            app.root.update()
            app.root.update_idletasks()

            win_right = app.root.winfo_rootx() + app.root.winfo_width()
            self.assertEqual(app.root.winfo_width(), 960)

            for btn in self._collect(app.step_frames[1], tk.Button):
                if not btn.winfo_ismapped():
                    continue
                right = btn.winfo_rootx() + btn.winfo_width()
                self.assertLessEqual(
                    right, win_right + 1,
                    "button %r overflows: right=%s, window right=%s"
                    % (btn.cget("text"), right, win_right))

            entry = next(c for c in app.tar_upload_frame.winfo_children()
                         if isinstance(c, tk.Entry))
            self.assertGreater(
                entry.winfo_width(), 150,
                "input field collapsed instead of expanding")
        finally:
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()

