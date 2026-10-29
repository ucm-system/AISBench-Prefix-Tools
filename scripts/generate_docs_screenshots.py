#!/usr/bin/env python3
"""Generate fresh user-guide screenshots from the current GUI implementation.

The script intentionally populates sample values instead of connecting to a
remote host. Run it from the repository root:

    python scripts/generate_docs_screenshots.py
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import COLOR_SUCCESS
from PIL import ImageGrab


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "images"


class FakeDockerManager:
    """Minimal DockerManager stand-in used only for screenshot state."""

    container_name = "aisbench-test-10281120"
    image_name = "aisbench:v3.1-20261013-master"
    code_mount_path = (
        "/benchmark/ais_bench/aisbench_auto_tools_prefix-main"
    )


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


def prepare_window(app):
    app.root.title("AISBenchPrefixTools")
    app.root.geometry("1180x800+40+40")
    app.root.attributes("-topmost", True)
    app.root.update_idletasks()
    app.root.update()


def populate_step1(app):
    app.conn_vars["host"].set("192.168.1.30")
    app.conn_vars["port"].set("22")
    app.conn_vars["user"].set("root")
    app.conn_password.set("aisbench-demo")
    app.conn_key.set("")
    app.conn_status_lbl.config(text="✓ 连接成功: 192.168.1.30:22",
                               fg=COLOR_SUCCESS)


def populate_step2(app):
    app._show_step(1)

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

    app.model_path_var.set("/mnt/models/DeepSeek-V4-Flash-w8a8-mtp")
    app.model_name_var.set("ds")
    app.host_ip_var.set("192.168.1.30")
    app.host_port_var.set("8000")
    app.api_key_var.set("")
    app.work_dir_var.set("/tmp/AISBench_Prefix_Tools")
    app.work_dir_status.config(text="部署后已自动清理", fg=COLOR_SUCCESS)
    app.residual_status_lbl.config(text="无残留容器", fg=COLOR_SUCCESS)

    app.docker = FakeDockerManager()
    app.docker_info_labels["tar"].config(
        text="aisbench:v3.1-20261013-master"
    )
    app.docker_info_labels["zip"].config(text="内置代码包")
    app.docker_info_labels["model"].config(
        text="/mnt/models/DeepSeek-V4-Flash-w8a8-mtp"
    )
    app.docker_info_labels["image"].config(
        text="aisbench:v3.1-20261013-master"
    )
    app.docker_info_labels["container"].config(
        text="aisbench-test-10281120"
    )

    app.deploy_btn.config(text="重新部署")
    app.docker_log.delete(1.0, "end")
    app.docker_log.insert(
        "1.0",
        "\n".join([
            "[1/5] 检查Docker环境...",
            "  ✓ Docker version 27.3.1, build 6d40811d5c",
            "",
            "[2/5] 准备AISBench镜像...",
            "  ✓ 复用执行机已有镜像: aisbench:v3.1-20261013-master",
            "  → 跳过镜像上传和docker load",
            "",
            "[3/5] 暂存内置测试代码...",
            "  ✓ 代码暂存完成: /tmp/AISBench_Prefix_Tools/aisbench_auto_tools_prefix-main",
            "",
            "[4/5] 创建并启动容器...",
            "  ✓ 容器 aisbench-test-10281120 已启动运行",
            "",
            "[5/5] 导入测试代码到容器并清理暂存目录...",
            "  ✓ 代码已就绪(容器内): /benchmark/ais_bench/aisbench_auto_tools_prefix-main",
            "  ✓ 已删除宿主机临时目录",
            "  ✓ 部署完成!",
        ]),
    )


def populate_step3(app):
    app._show_step(2)

    app.config_entry_vars["model_name"].set("ds")
    app.config_entry_vars["model_path"].set(
        "/mnt/models/DeepSeek-V4-Flash-w8a8-mtp"
    )
    app.config_entry_vars["host_ip"].set("192.168.1.30")
    app.config_entry_vars["host_port"].set("8000")
    app.config_entry_vars["api_key"].set("")
    app.config_entry_vars["dataset_path"].set(
        "/benchmark/ais_bench/aisbench_auto_tools_prefix-main"
    )
    app.config_entry_vars["work_path"].set("/benchmark")
    app.config_entry_vars["default_perf"].set("default_perf")
    app.config_entry_vars["output_dir"].set("./outputs/default")
    app.config_entry_vars["pod_info"].set("")
    app._sync_config_vars()
    app.config_status_lbl.config(text="✓ 已保存并验证通过", fg=COLOR_SUCCESS)


def populate_step4(app):
    app._show_step(3)

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


def populate_step5(app):
    app._show_step(4)

    app.local_output_var.set(r"C:\Users\tester\aisbench_results")
    app._refresh_commands()
    app.exec_test_btn.config(text="重新执行测试")
    app.cleanup_btn.config(state="normal")

    app.exec_log.delete(1.0, "end")
    app.exec_log.insert(
        "1.0",
        "\n".join([
            "[0/4] 预检查: 验证容器内MODEL_PATH...",
            "  ✓ OK: MODEL_PATH=/mnt/models/DeepSeek-V4-Flash-w8a8-mtp",
            "[1/4] 生成测试脚本...",
            "  ✓ run_tests.sh (写入容器内部)",
            "[2/4] 写入测试脚本到容器并执行...",
            "  ✓ 测试脚本执行完成",
            "[3/4] 下载测试日志到本地...",
            "  容器内日志目录: /benchmark/ais_bench/aisbench_auto_tools_prefix-main/test_logs_20261029_1120",
            "  共下载 4 个日志文件",
            "[4/4] 解析日志生成CSV结果...",
            "  ✓ CSV生成完成: results_test_logs_20261029_1120.csv",
        ]),
    )

    sample_results = [
        (16384, 512, 108, 46, 46, 4523.1, 312.5, 45.2, 12.3, 8.5, 92.3, 91.8),
        (16384, 1024, 108, 45, 45, 4410.8, 290.1, 48.1, 11.8, 7.2, 92.5, 91.6),
        (32768, 512, 54, 23, 23, 3895.4, 201.7, 52.6, 13.1, 6.1, 94.8, 95.1),
        (32768, 1024, 54, 22, 22, 3748.2, 188.4, 56.9, 12.9, 5.4, 95.0, 94.7),
    ]
    for item in app.results_tree.get_children():
        app.results_tree.delete(item)
    for row in sample_results:
        app.results_tree.insert("", "end", values=row)
    app.results_info_lbl.config(
        text="共 4 条记录  |  CSV: results_test_logs_20261029_1120.csv  |  "
             "日志: test_logs_20261029_1120"
    )


def main():
    import main as app_module

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = app_module.WizardApp()
    prepare_window(app)

    populate_step1(app)
    app._show_step(0)
    capture(app, "step1-connection-20261029.png")

    populate_step2(app)
    capture(app, "step2-docker-20261029.png")

    populate_step3(app)
    capture(app, "step3-config-20261029.png")

    populate_step4(app)
    capture(app, "step4-testcases-20261029.png")

    populate_step5(app)
    capture(app, "step5-execute-20261029.png")

    app.root.destroy()


if __name__ == "__main__":
    main()
