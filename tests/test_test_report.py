#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单次测试执行HTML报告生成测试"""
import tempfile
import unittest
from pathlib import Path

from test_report import _interpret_results, render_test_report
from kvcache_animation import (_scenario_text,
                               render_kvcache_animation_html)


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
                status="completed",
                cache_info={"single_kv_cache": 1000000, "dp": 4,
                            "total_kv_cache": 4000000,
                            "max_request_length": 32768,
                            "repeat_rate": 0.9, "request_rate": 0})

            self.assertEqual(result, path)
            text = Path(path).read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<!DOCTYPE html>"))
            self.assertIn("AISBench 测试报告", text)
            self.assertIn("夜间基线", text)
            self.assertIn("已完成", text)
            # 五个主要章节都存在
            for section in ["模型与服务", "测试配置", "执行环境", "执行命令",
                            "测试结果", "结果解读", "KV Cache 命中过程动画"]:
                self.assertIn(section, text)
            # 模型/配置/命令/结果内容
            self.assertIn("Qwen-72B", text)
            self.assertIn("Burst (0)", text)
            self.assertIn("aisbench_test.py --input_len 4096", text)
            self.assertIn("4K", text)          # 输入长度格式化
            self.assertIn("850.4", text)       # 输出吞吐
            self.assertIn("AISBench-Prefix-Tools", text)
            # 动画章节: 每个用例一个动画块, 默认显示第一个用例
            self.assertIn('id="animCase0"', text)
            self.assertIn('id="animCase1" hidden', text)
            self.assertIn('id="animCanvas0"', text)
            self.assertIn('id="animCanvas1"', text)
            self.assertIn('id="animTabs"', text)
            self.assertIn("阶段一：KV Cache 预埋", text)
            self.assertIn("阶段二：正式测试", text)
            # 测试结果行可点击切换到对应用例动画
            self.assertIn('class="case-row" data-case="0"', text)
            self.assertIn('class="case-row" data-case="1"', text)
            self.assertIn("点击用例行", text)
            # 动画数据与场景解读
            self.assertIn("总 KV cache 4,000,000 tokens", text)
            self.assertIn("预埋 KV 需求 ≈ 4,096,000 tokens", text)
            self.assertIn("HBM 命中率 92.1%", text)
            self.assertIn("直接在 HBM 中命中", text)
            # 场景解读包含用户指定的关键语义说明
            self.assertIn("加载回 HBM", text)
            self.assertIn("attention 计算", text)
            self.assertIn("prefill 重新计算", text)

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

    def test_animation_section_with_empty_results(self):
        html_text = render_kvcache_animation_html([], {})
        self.assertIn("KV Cache 命中过程动画", html_text)
        self.assertIn("未提取到有效结果，无法生成命中过程动画", html_text)

    def test_animation_all_cases_have_scenario_and_canvas(self):
        html_text = render_kvcache_animation_html(
            _sample_results(),
            {"total_kv_cache": 4000000, "repeat_rate": 0.9})
        # 两个用例各有一个canvas与解读块
        self.assertEqual(html_text.count('class="anim-canvas"'), 2)
        self.assertEqual(html_text.count("命中过程解读"), 2)
        self.assertIn("用例 1 · 4K/1K", html_text)
        self.assertIn("用例 2 · 16K/2K", html_text)


class InterpretResultsTests(unittest.TestCase):
    def test_empty_results_gives_warning(self):
        notes = _interpret_results([])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0][0], "warning")

    def test_notes_are_descriptive_without_judgments(self):
        results = [_sample_results()[0]]
        notes = _interpret_results(results)
        text = " ".join(text for _l, text in notes)
        # 每个指标都有含义说明和具体数值, 不包含正常/异常判断
        self.assertIn("HBM", text)
        self.assertIn("92.1", text)
        for keyword in ["TTFT", "TPOT", "输出吞吐", "QPS", "E2E"]:
            self.assertIn(keyword, text)
        for judgment in ["较高", "偏低", "良好", "建议", "可能超出"]:
            self.assertNotIn(judgment, text)


class ScenarioTextTests(unittest.TestCase):
    def test_hbm_zero_external_zero_explains_lru_and_eviction(self):
        text = _scenario_text(0, 0, 0.9)
        self.assertIn("HBM 命中率为 0%", text)
        self.assertIn("把 HBM 显存空间占满", text)
        self.assertIn("LRU 策略", text)
        self.assertIn("覆盖/逐出", text)
        self.assertIn("没有被写入外置存储", text)
        self.assertIn("超过了外置存储容量", text)

    def test_hbm_zero_external_hit_explains_load_back(self):
        text = _scenario_text(0, 61.5, 0.9)
        self.assertIn("外部命中率为 61.5%", text)
        self.assertIn("在外置存储中找到", text)
        self.assertIn("加载回 HBM", text)
        self.assertIn("attention 计算", text)

    def test_hbm_hit_explains_direct_attention_use(self):
        text = _scenario_text(92.1, 5.4, 0.9)
        self.assertIn("HBM 命中率为 92.1%", text)
        self.assertIn("直接在 HBM 中命中", text)
        self.assertIn("repeat_rate = 90%", text)
        self.assertIn("仍有约 2.5%", text)


if __name__ == "__main__":
    unittest.main()
