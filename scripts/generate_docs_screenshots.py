#!/usr/bin/env python3
"""Generate fresh user-guide screenshots from the current GUI implementation.

The script intentionally populates sample values instead of connecting to a
remote host, and injects demo tasks into a temporary TaskManager so the Task
List page can be captured. Run it from the repository root:

    python scripts/generate_docs_screenshots.py
"""

from datetime import datetime
from pathlib import Path
import shutil
import sys
import tempfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import COLOR_SUCCESS
from i18n import set_language
from PIL import ImageGrab


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "images"
DATE = "20261102"


def capture(app, filename):
    app.root.update_idletasks()
    app.root.update()

    x = app.root.winfo_rootx()
    y = app.root.winfo_rooty()
    width = app.root.winfo_width()
    height = app.root.winfo_height()

    path = OUTPUT_DIR / filename
    ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(path)
    print(f"saved {path}")


def capture_window(window, filename):
    window.update_idletasks()
    window.update()

    x = window.winfo_rootx()
    y = window.winfo_rooty()
    width = window.winfo_width()
    height = window.winfo_height()

    path = OUTPUT_DIR / filename
    ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(path)
    print(f"saved {path}")


def prepare_window(app):
    app.root.title("AISBenchPrefixTools")
    app.root.geometry("1180x840+40+20")
    app.root.attributes("-topmost", True)
    app.root.update_idletasks()
    app.root.update()


def scroll_to_widget(app, widget, top_margin=0.05):
    """滚动到指定控件(用于对合并后的长页面分段截图)"""
    y = 0
    node = widget
    while node is not None and node is not app.content_container:
        y += node.winfo_y()
        node = node.master

    total = app.content_container.winfo_reqheight()
    view = app._content_canvas.winfo_height()
    scrollable = max(1, total - view)
    fraction = max(0.0, min(1.0, (y - int(top_margin * view)) / scrollable))
    app._content_canvas.yview_moveto(fraction)
    app.root.update_idletasks()
    app.root.update()


def capture_section(app, anchor, filename):
    scroll_to_widget(app, anchor)
    capture(app, filename)


def populate_step1(app):
    app.conn_vars["host"].set("192.168.1.30")
    app.conn_vars["port"].set("22")
    app.conn_vars["user"].set("root")
    app.conn_password.set("aisbench-demo")
    app.conn_key.set("")
    app.conn_status_lbl.config(text="✓ 连接成功: 192.168.1.30:22",
                               fg=COLOR_SUCCESS)


def populate_task_resources(app):
    app._show_step(1)

    app.task_name_var.set("ds_w8a8_dp4")

    app.remote_images = [
        {
            "name": "aisbench:v3.1-20261013-master",
            "id": "8f21c9a4e712",
            "created": "3 days ago",
            "size": "14.2GB",
        },
        {
            "name": "ubuntu:24.04",
            "id": "ca1b6d73a10c",
            "created": "1 month ago",
            "size": "78.1MB",
        },
    ]
    app.remote_image_combo.config(
        values=[image["name"] for image in app.remote_images]
    )
    app.remote_image_var.set(app.remote_images[0]["name"])
    app.image_source_var.set("existing")
    app._on_image_source_change()
    app._on_remote_image_selected()
    app.image_list_status.config(text="共 2 个镜像", fg=COLOR_SUCCESS)

    app.model_path_var.set("/mnt/models/DeepSeek-V4-Flash-w8a8-mtp")
    app.work_dir_var.set("/tmp/AISBench_Prefix_Tools")
    app.code_source_var.set("builtin")
    app.residual_status_lbl.config(text="无残留容器", fg=COLOR_SUCCESS)


def populate_task_service(app):
    app.model_name_var.set("ds")
    app.host_ip_var.set("192.168.1.30")
    app.host_port_var.set("8000")
    app.api_key_var.set("")
    app.pod_info_var.set("")


def populate_task_testcases(app):
    app.kv_cache_var.set("198469")
    app.dp_var.set("4")
    app.max_req_len_var.set("131072")
    app.repeat_rate_var.set("0.9")
    app.request_rate_var.set("0")

    app.designer.set_kv_cache_info(198469, 4, 131072)
    app.designer.set_repeat_rate(0.9)
    app.designer.set_request_rate(0)
    app.designer.set_input_lengths([16384, 32768])
    app.designer.set_output_lengths([512, 1024])
    app.designer.generate_test_cases()

    for length, var in app.input_length_vars.items():
        var.set(length in (16384, 32768))
    for length, var in app.output_length_vars.items():
        var.set(length in (512, 1024))

    app._refresh_test_tree()
    app._show_calc_details()


def populate_task_run(app):
    app.local_output_var.set(r"C:\Users\tester\aisbench_results")


SAMPLE_TASK_LOG = "\n".join([
    "===== 创建任务 ds_w8a8_dp4 (2026-11-02 15:30:00) =====",
    "[连接] 建立任务独立SSH连接...",
    "  ✓ SSH连接成功: root@192.168.1.30:22",
    "[部署] 使用临时部署目录: /tmp/AISBench_Prefix_Tools/task_ds_w8a8_dp4_153000",
    "  ✓ 镜像已存在, 跳过上传: aisbench:v3.1-20261013-master",
    "[3/5] 创建并启动容器...",
    "  ✓ 容器 aisbench-test-ds-w8a8-dp4-1530 已启动",
    "[4/5] 导入测试代码到容器...",
    "  ✓ 代码导入完成",
    "[5/5] 清理宿主机临时目录...",
    "  ✓ 临时目录已删除",
    "  ✓ config.py已写入并验证一致",
    "    MODEL_PATH=/mnt/models/DeepSeek-V4-Flash-w8a8-mtp  MODEL_NAME=ds  HOST=192.168.1.30:8000",
    "[测试] 预检查: 验证容器内MODEL_PATH...",
    "  ✓ OK: MODEL_PATH 存在且包含 config.json",
    "[测试] 生成测试脚本...",
    "[测试] 写入测试脚本到容器并执行 (可能耗时较长)...",
    "POST=108/108 | 46并发 | 16384+512",
    "POST=108/108 | 45并发 | 16384+1024",
    "POST=54/54 | 23并发 | 32768+512",
    "POST=54/54 | 22并发 | 32768+1024",
    "  ✓ 测试脚本执行完成",
    "[测试] 下载测试日志到本地...",
    "  ✓ 已下载 4 个日志文件到 C:\\Users\\tester\\aisbench_results\\test_logs_20261102_153000",
    "[测试] 解析日志生成CSV结果...",
    "  CSV文件: C:\\Users\\tester\\aisbench_results\\results_test_logs_20261102_153000.csv",
    "✓ 测试完成! 共 4 条结果",
    "",
    "===== 任务执行完成 =====",
]) + "\n"


SAMPLE_TASK_RESULTS = [
    {"input_len": 16384, "output_len": 512, "total_req": 108,
     "max_cc": 46, "cc": 46, "input_token_throughput": 4523.1,
     "output_throughput": 312.5, "TTFT_avg": 45.2, "TPOT_avg": 12.3,
     "qps": 8.5, "hbm_hit_rate": 92.3, "external_hit_rate": 91.8},
    {"input_len": 16384, "output_len": 1024, "total_req": 108,
     "max_cc": 45, "cc": 45, "input_token_throughput": 4410.8,
     "output_throughput": 290.1, "TTFT_avg": 48.1, "TPOT_avg": 11.8,
     "qps": 7.2, "hbm_hit_rate": 92.5, "external_hit_rate": 91.6},
    {"input_len": 32768, "output_len": 512, "total_req": 54,
     "max_cc": 23, "cc": 23, "input_token_throughput": 3895.4,
     "output_throughput": 201.7, "TTFT_avg": 52.6, "TPOT_avg": 13.1,
     "qps": 6.1, "hbm_hit_rate": 94.8, "external_hit_rate": 95.1},
    {"input_len": 32768, "output_len": 1024, "total_req": 54,
     "max_cc": 22, "cc": 22, "input_token_throughput": 3748.2,
     "output_throughput": 188.4, "TTFT_avg": 56.9, "TPOT_avg": 12.9,
     "qps": 5.4, "hbm_hit_rate": 95.0, "external_hit_rate": 94.7},
]


def build_demo_task(app, task_id, name, status, log_dir,
                    created, finished=None, with_results=True):
    from task_manager import Task, TaskInputs, TaskStatus

    inputs = TaskInputs(
        name=name,
        image_mode="existing",
        selected_image="aisbench:v3.1-20261013-master",
        code_source="builtin",
        model_path="/mnt/models/DeepSeek-V4-Flash-w8a8-mtp",
        work_dir_base="/tmp/AISBench_Prefix_Tools",
        model_name="ds",
        host_ip="192.168.1.30",
        host_port="8000",
        local_output=r"C:\Users\tester\aisbench_results",
    )
    log_path = Path(log_dir) / f"{task_id}.log"
    task = Task(task_id, inputs, None, log_path)
    task.status = status
    task.created_at = created
    task.finished_at = finished
    task.container_name = f"aisbench-test-{name.lower().replace('_', '-')}"
    task.image_name = "aisbench:v3.1-20261013-master"
    task.csv_path = (r"C:\Users\tester\aisbench_results"
                     r"\results_test_logs_20261102_153000.csv")
    task.result_dir = r"C:\Users\tester\aisbench_results"
    task.results = SAMPLE_TASK_RESULTS if with_results else []
    task.log_buffer.open()
    task.log_buffer.append(SAMPLE_TASK_LOG if with_results
                           else SAMPLE_TASK_LOG.split("[测试]")[0])
    return task


def populate_tasklist(app, log_dir):
    from task_manager import TaskStatus

    done = build_demo_task(
        app, "t1", "ds_w8a8_dp4", TaskStatus.COMPLETED, log_dir,
        datetime(2026, 11, 2, 15, 30, 0),
        datetime(2026, 11, 2, 15, 41, 12))
    running = build_demo_task(
        app, "t2", "ds_w8a8_dp4_run2", TaskStatus.RUNNING, log_dir,
        datetime(2026, 11, 2, 15, 45, 0), with_results=False)
    app.task_manager.tasks = {"t1": done, "t2": running}

    app._show_step(2)
    app._refresh_task_table()
    app._select_task("t1", reset_log=True)
    app._update_task_results_view()
    app._update_task_log_view(force=True)
    app.root.update_idletasks()
    app.root.update()
    return done


def capture_task_info_dialog(app):
    """弹出"预览任务信息"对话框并截图"""
    app._show_task_info_dialog(execute=False)
    app.root.update_idletasks()
    app.root.update()
    # 最新的Toplevel即预览对话框
    children = [w for w in app.root.winfo_children()
                if isinstance(w, __import__("tkinter").Toplevel)]
    if children:
        dlg = children[-1]
        dlg.geometry("860x700+120+60")
        capture_window(dlg, f"step2-task-preview-{DATE}.png")
        dlg.destroy()


def main():
    import main as app_module

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_dir = tempfile.mkdtemp(prefix="aisbench-shots-")
    settings_file = Path(tempfile.mkdtemp(prefix="aisbench-settings-")) / "settings.json"
    try:
        with mock.patch("settings_manager.settings_path",
                        return_value=settings_file):
            app = app_module.WizardApp()
            prepare_window(app)

            # ---- 步骤1: SSH连接 ----
            populate_step1(app)
            app._show_step(0)
            capture(app, f"step1-connection-{DATE}.png")

            # ---- 步骤2: 创建任务(四个分区) ----
            populate_task_resources(app)
            populate_task_service(app)
            populate_task_testcases(app)
            populate_task_run(app)

            capture_section(app, app.resources_section_header,
                            f"step2-task-resources-{DATE}.png")
            capture_section(app, app.service_section_header,
                            f"step2-task-service-{DATE}.png")
            capture_section(app, app.testcases_section_header,
                            f"step2-task-testcases-{DATE}.png")
            capture_section(app, app.run_section_header,
                            f"step2-task-run-{DATE}.png")
            capture_task_info_dialog(app)

            # ---- 步骤3: 任务列表 ----
            task = populate_tasklist(app, log_dir)
            capture(app, f"step3-tasklist-{DATE}.png")

            # ---- 英文界面 ----
            set_language("en")
            app._rebuild_ui_for_language()
            prepare_window(app)
            populate_task_resources(app)
            populate_task_service(app)
            populate_task_testcases(app)
            populate_task_run(app)
            capture_section(app, app.resources_section_header,
                            f"step2-task-resources-en-{DATE}.png")

            app.task_manager.tasks = {"t1": task}
            app._show_step(2)
            app._refresh_task_table()
            app._select_task("t1", reset_log=True)
            app._update_task_results_view()
            app._update_task_log_view(force=True)
            prepare_window(app)
            capture(app, f"step3-tasklist-en-{DATE}.png")

            app.root.destroy()
    finally:
        # 关闭demo任务的日志文件句柄再清理临时目录
        for task in app.task_manager.tasks.values():
            try:
                task.log_buffer.close()
            except Exception:
                pass
        shutil.rmtree(log_dir, ignore_errors=True)
        shutil.rmtree(str(settings_file.parent), ignore_errors=True)


if __name__ == "__main__":
    main()
