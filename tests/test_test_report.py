#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单次测试执行HTML报告生成测试"""
import tempfile
import unittest
from pathlib import Path

from test_report import _interpret_results, render_test_report


def _sample_results():
    return [
        {"input_len": 4096, "output_len": 1024, "total_req": 1000,
         "max_cc": 100, "cc": 80, "TTFT_avg": "120.5",
         "TPOT_avg": "15.2", "output_throughput": "850.4",
         "input_token_throughput": "3400.0", "qps": "12.3",
         "hbm_hit_rate": 92.1, "external_hit_rate": 5.4,
         "E2E_time": "81.2"},
        {"input_len": 16384, "output_len": 2048, "total_req": 1000,
         "max_cc": 100, "cc": 80, "TTFT_avg": "210.8",
         "TPOT_avg": "18.9", "output_throughput": "640.2",
         "input_token_throughput": "5100.0", "qps": "9.8",
         "hbm_hit_rate": 88.7, "external_hit_rate": 8.1,
         "E2E_time": "102.3"},
    ]


class RenderTestReportTests(unittest.TestCase):
    def test_report_contains_all_sections_and_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "report_test.html")
            result = render_test_report(
                path, task_name="夜间基线",
                model_info={"MODEL_NAME (模型名称)": "Qwen-72B",
                            "MODEL_PATH (模型路径)": "/mnt/models/qwen",
                            "HOST_IP (vLLM服务IP)": "10.0.0.1",
                            "HOST_PORT (vLLM服务端口)": "8000"},
                test_config={"DP组数": "4", "前缀命中率 (repeat_rate)": "90%",
                             "请求发送速率": "Burst (0)", "测试用例数": "2"},
                commands=["python3 aisbench_test.py --input_len 4096",
                          "python3 aisbench_test.py --input_len 16384"],
                results=_sample_results(),
                environment={"容器名称": "aisbench-test-0101", "结果目录": tmp},
                status="completed")

            self.assertEqual(result, path)
            text = Path(path).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<!DOCTYPE html>"))
            self.assertIn("AISBench 测试报告", text)
            self.assertIn("夜间基线", text)
            self.assertIn("已完成", text)
            # 五个主要章节都存在
            for section in ["模型与服务", "测试配置", "执行环境", "执行命令",
                            "测试结果", "结果解读"]:
                self.assertIn(section, text)
            # 模型/配置/命令/结果内容
            self.assertIn("Qwen-72B", text)
            self.assertIn("Burst (0)", text)
            self.assertIn("aisbench_test.py --input_len 4096", text)
            self.assertIn("4K", text)          # 输入长度格式化
            self.assertIn("850.4", text)       # 输出吞吐
            self.assertIn("AISBench-Prefix-Tools", text)

    def test_report_with_empty_results_and_abnormal_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "report_empty.html")
            render_test_report(
                path, task_name="失败任务", model_info={}, test_config={},
                commands=[], results=[], environment={},
                status="abnormal")
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("异常终止", text)
            self.assertIn("未提取到有效结果", text)
            self.assertIn("无模型信息", text)


class InterpretResultsTests(unittest.TestCase):
    def test_empty_results_gives_warning(self):
        notes = _interpret_results([])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0][0], "warning")

    def test_high_hbm_hit_is_good(self):
        results = [_sample_results()[0]]
        notes = _interpret_results(results)
        levels = [level for level, _text in notes]
        self.assertIn("good", levels)
        text = " ".join(text for _l, text in notes)
        self.assertIn("HBM", text)
        self.assertIn("92.1", text)


if __name__ == "__main__":
    unittest.main()
