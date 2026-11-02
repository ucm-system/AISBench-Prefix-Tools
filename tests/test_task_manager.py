"""任务管理模块单元测试: 日志缓冲 / 输入快照 / 生命周期 / 持久化"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import i18n
from task_manager import (
    TaskInputs,
    TaskLogBuffer,
    TaskManager,
    TaskStatus,
    auto_task_name,
    sanitize_task_name,
    status_label,
)


class TaskLogBufferTests(unittest.TestCase):
    def test_plain_lines_are_committed_and_polled(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        buf = TaskLogBuffer(Path(tmp.name) / "task.log")
        buf.open()
        self.addCleanup(buf.close)
        buf.append("hello\nworld\n")
        new, pending = buf.poll()
        self.assertEqual(new, ["hello", "world"])
        self.assertEqual(pending, "")
        # 第二次poll无新增
        self.assertEqual(buf.poll(), ([], ""))

    def test_carriage_return_progress_replaces_pending(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        buf = TaskLogBuffer(Path(tmp.name) / "task.log")
        self.addCleanup(buf.close)
        buf.append("\r  上传中: 10%\r  上传中: 50%")
        new, pending = buf.poll()
        self.assertEqual(new, [])
        self.assertIn("50%", pending)
        self.assertNotIn("10%", pending)

    def test_status_lines_fold_to_latest(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        buf = TaskLogBuffer(Path(tmp.name) / "task.log")
        self.addCleanup(buf.close)
        buf.append("POST=100 ...\nPOST=200 ...\nPOST=300 ...\ndone\n")
        new, pending = buf.poll()
        # 折叠后只保留最新一条状态行 + 后续普通行
        joined = "\n".join(new)
        self.assertIn("POST=300", joined)
        self.assertNotIn("POST=100", joined)
        self.assertNotIn("POST=200", joined)
        self.assertIn("done", joined)

    def test_ansi_escape_codes_are_stripped(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        buf = TaskLogBuffer(Path(tmp.name) / "task.log")
        self.addCleanup(buf.close)
        buf.append("\x1b[32mOK\x1b[0m\n")
        new, _ = buf.poll()
        self.assertEqual(new, ["OK"])

    def test_finalize_commits_pending(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "task.log"
        buf = TaskLogBuffer(path)
        buf.open()
        self.addCleanup(buf.close)
        buf.append("partial line without newline")
        buf.finalize()
        new, pending = buf.poll()
        self.assertEqual(new, ["partial line without newline"])
        self.assertEqual(pending, "")
        # 已落地到本地日志文件
        content = path.read_text(encoding="utf-8")
        self.assertIn("partial line without newline", content)


class TaskInputTests(unittest.TestCase):
    def test_custom_name_is_used(self):
        inputs = TaskInputs(name="my-task", model_name="ds")
        self.assertEqual(inputs.resolved_name(), "my-task")

    def test_empty_name_auto_generates_service_timestamp(self):
        inputs = TaskInputs(name="", model_name="qwen")
        name = inputs.resolved_name()
        self.assertTrue(name.startswith("qwen_"))
        self.assertRegex(name, r"qwen_\d{8}_\d{6}")

    def test_empty_service_falls_back_to_ds(self):
        name = auto_task_name("")
        self.assertTrue(name.startswith("ds_"))

    def test_to_dict_from_dict_roundtrip(self):
        inputs = TaskInputs(
            name="t1", image_mode="upload", tar_path="a.tar",
            model_path="/models/x", kv_cache="1024", dp="2",
            input_lengths=[8192, 16384], output_lengths=[512],
            cases=[{"input_len": 8192, "output_len": 512,
                    "data_num_recommended": 10, "data_num_min": 5,
                    "concurrency_recommended": 4, "concurrency_max": 8,
                    "prefix_num": 10, "repeat_rate": 0.9, "dp": 2,
                    "is_custom": False}],
            local_output="C:/out",
        )
        clone = TaskInputs.from_dict(inputs.to_dict())
        self.assertEqual(clone.tar_path, "a.tar")
        self.assertEqual(clone.input_lengths, [8192, 16384])
        self.assertEqual(clone.cases[0]["prefix_num"], 10)

    def test_sanitize_task_name_replaces_unsafe_chars(self):
        # 纯中文/特殊字符名清理后为空, 回退为通用名
        self.assertEqual(sanitize_task_name("任务/名称:测试"), "task")
        self.assertEqual(sanitize_task_name("ok.name-1"), "ok.name-1")
        self.assertEqual(sanitize_task_name(""), "task")
        self.assertLessEqual(len(sanitize_task_name("a" * 100)), 40)


class TaskManagerTests(unittest.TestCase):
    def _manager(self) -> TaskManager:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mgr = TaskManager(data_dir=Path(tmp.name))
        self.addCleanup(mgr.shutdown)
        return mgr

    def _inputs(self, name="task-a", **kw):
        defaults = dict(
            name=name, image_mode="existing", selected_image="img:latest",
            model_path="/models/m", kv_cache="1024", dp="1",
            max_req_len="32768", repeat_rate="0.9", request_rate="0",
            input_lengths=[8192], output_lengths=[512],
            cases=[{"input_len": 8192, "output_len": 512,
                    "data_num_recommended": 10, "data_num_min": 5,
                    "concurrency_recommended": 4, "concurrency_max": 8,
                    "prefix_num": 10, "repeat_rate": 0.9, "dp": 1,
                    "is_custom": False}],
            local_output="out",
        )
        defaults.update(kw)
        return TaskInputs(**defaults)

    def test_create_task_writes_index_and_log_file(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(), {"host": "h"})
        self.assertEqual(task.status, TaskStatus.QUEUED)
        self.assertIn(task.id, mgr.tasks)
        index = json.loads(mgr.index_path.read_text(encoding="utf-8"))
        self.assertEqual(len(index["tasks"]), 1)
        self.assertEqual(index["tasks"][0]["name"], "task-a")
        # 敏感信息不落盘
        self.assertNotIn("password", json.dumps(index))
        # 日志文件已创建
        self.assertTrue(task.log_buffer.log_path.exists())

    def test_load_marks_active_tasks_interrupted(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(), {"host": "h"})
        # 模拟程序重启: 直接重新加载同一数据目录
        mgr2 = TaskManager(data_dir=mgr.data_dir)
        loaded = mgr2.get(task.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, TaskStatus.INTERRUPTED)
        self.assertEqual(loaded.inputs.model_path, "/models/m")

    def test_terminal_task_status_roundtrip(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(), {"host": "h"})
        task.set_status(TaskStatus.COMPLETED)
        task.csv_path = "out/r.csv"
        mgr.save_index()
        mgr2 = TaskManager(data_dir=mgr.data_dir)
        loaded = mgr2.get(task.id)
        self.assertEqual(loaded.status, TaskStatus.COMPLETED)
        self.assertEqual(loaded.csv_path, "out/r.csv")

    def test_delete_task_removes_record_and_files(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(), {"host": "h"})
        task.set_status(TaskStatus.COMPLETED)
        # 生成任务数据文件
        result_dir = Path(mgr.data_dir) / "results"
        result_dir.mkdir(parents=True)
        (result_dir / "r.csv").write_text("x", encoding="utf-8")
        task.csv_path = str(result_dir / "r.csv")
        mgr.save_index()

        self.assertTrue(mgr.delete_task(task.id, delete_files=True))
        self.assertIsNone(mgr.get(task.id))
        self.assertFalse((result_dir / "r.csv").exists())
        index = json.loads(mgr.index_path.read_text(encoding="utf-8"))
        self.assertEqual(index["tasks"], [])

    def test_delete_active_task_is_rejected(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(), {"host": "h"})
        task.set_status(TaskStatus.RUNNING)
        self.assertFalse(mgr.delete_task(task.id))
        self.assertIsNotNone(mgr.get(task.id))

    def test_cancel_task_sets_flag(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(), {"host": "h"})
        task.set_status(TaskStatus.DEPLOYING)
        self.assertTrue(mgr.cancel_task(task.id))
        self.assertTrue(task.cancel_flag.is_set())
        # 已终态任务不可取消
        task.set_status(TaskStatus.COMPLETED)
        self.assertFalse(mgr.cancel_task(task.id))

    def test_copy_inputs_returns_independent_snapshot(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(name="origin"), {"host": "h"})
        copied = mgr.copy_inputs(task.id)
        self.assertEqual(copied.model_path, "/models/m")
        copied.model_path = "/other"
        self.assertEqual(task.inputs.model_path, "/models/m")

    def test_start_task_rejects_non_queued(self):
        mgr = self._manager()
        task = mgr.create_task(self._inputs(), {"host": "h"})
        task.set_status(TaskStatus.COMPLETED)
        self.assertFalse(mgr.start_task(task.id))

    def test_all_tasks_sorted_by_created_desc(self):
        mgr = self._manager()
        t1 = mgr.create_task(self._inputs(name="t1"), {"host": "h"})
        time.sleep(0.02)
        t2 = mgr.create_task(self._inputs(name="t2"), {"host": "h"})
        tasks = mgr.all_tasks()
        self.assertEqual(tasks[0].id, t2.id)
        self.assertEqual(tasks[1].id, t1.id)


class StatusLabelTests(unittest.TestCase):
    def test_known_status_has_label(self):
        for status in TaskStatus.ALL:
            self.assertTrue(status_label(status))

    def test_unknown_status_falls_back(self):
        self.assertEqual(status_label("weird"), "weird")


if __name__ == "__main__":
    unittest.main()
