# -*- coding: utf-8 -*-
"""结果对比功能测试: 自定义标注 + PNG图片导出"""
import csv
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import result_compare
import i18n
from result_compare import (ResultCompareDialog, render_chart_png,
                            sanitize_name, load_result_csv)
from log_parser import CSV_FIELDS


def _write_csv(path: Path, values):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for base in values:
            row = {field: "" for field in CSV_FIELDS}
            row.update({
                "input_len": base[0], "output_len": base[1],
                "total_req": 10000, "max_cc": 100, "cc": 80,
                "TTFT_avg": base[2], "TPOT_avg": base[3],
                "output_throughput": base[4], "qps": base[5],
                "hbm_hit_rate": base[6], "external_hit_rate": base[7],
            })
            writer.writerow(row)


def _sample_rows():
    return [
        (4096, 1024, "120.5", "15.2", "850.4", "12.3", "92.1", "5.4"),
        (16384, 2048, "210.8", "18.9", "640.2", "9.8", "88.7", "8.1"),
    ]


class SanitizeNameTests(unittest.TestCase):
    def test_replaces_unsafe_characters(self):
        self.assertEqual(sanitize_name("result_test_甲/乙:2*3"), "result_test_甲_乙_2_3")
        self.assertEqual(sanitize_name("   "), "run")
        self.assertEqual(sanitize_name(""), "run")
        self.assertEqual(sanitize_name("x" * 100, max_len=10), "xxxxxxxxxx")


class ResultCompareDialogTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

        self.csv_a = self.dir / "result_test_baseline_20261031.csv"
        self.csv_b = self.dir / "result_test_optimized_20261031.csv"
        _write_csv(self.csv_a, _sample_rows())
        _write_csv(self.csv_b, [
            (4096, 1024, "98.4", "13.1", "920.7", "14.1", "95.3", "3.2"),
            (16384, 2048, "180.2", "16.4", "705.9", "11.2", "91.8", "6.5"),
        ])

        self.dialog = ResultCompareDialog(self.root)
        # 自绘确认框会等待用户点击, 无头测试中必须替换为普通Mock。
        showinfo_patch = mock.patch("result_compare.showinfo")
        showinfo_patch.start()
        self.addCleanup(showinfo_patch.stop)
        self.addCleanup(self._close)

    def _close(self):
        try:
            self.dialog.dialog.destroy()
        finally:
            self.root.destroy()

    def test_browse_csv_auto_fills_label_from_filename(self):
        self.dialog.label_a_var.set("")
        with mock.patch("result_compare.filedialog.askopenfilename",
                        return_value=str(self.csv_a)):
            self.dialog._browse_csv(self.dialog.file_a_var)
        self.assertEqual(self.dialog.file_a_var.get(), str(self.csv_a))
        self.assertEqual(self.dialog.label_a_var.get(),
                         "result_test_baseline_20261031")

    def test_auto_fill_does_not_override_user_label(self):
        self.dialog.label_a_var.set("我的基线")
        with mock.patch("result_compare.filedialog.askopenfilename",
                        return_value=str(self.csv_a)):
            self.dialog._browse_csv(self.dialog.file_a_var)
        self.assertEqual(self.dialog.label_a_var.get(), "我的基线")
        self.assertEqual(self.dialog._label_a(), "我的基线")

    def test_label_falls_back_to_filename_then_ab(self):
        self.dialog.file_a_var.set(str(self.csv_a))
        self.dialog.label_a_var.set("")
        self.assertEqual(self.dialog._label_a(), "result_test_baseline_20261031")
        self.dialog.file_a_var.set("")
        self.assertEqual(self.dialog._label_a(), "A")

    def _load_and_compare(self, label_a="基线v1", label_b="优化后v2"):
        self.dialog.file_a_var.set(str(self.csv_a))
        self.dialog.file_b_var.set(str(self.csv_b))
        self.dialog.label_a_var.set(label_a)
        self.dialog.label_b_var.set(label_b)
        self.dialog._load_data()
        self.dialog._do_compare()
        self.assertTrue(self.dialog.compared)
        self.assertEqual(len(self.dialog.selected_matches), 2)

    def test_compare_uses_custom_labels_in_chart_legend(self):
        self._load_and_compare()
        charts = [c for c in self.dialog.charts_inner.winfo_children()
                  if isinstance(c, result_compare.BarChartWidget)]
        self.assertTrue(charts)
        for chart in charts:
            self.assertEqual(chart.name_a, "A: 基线v1")
            self.assertEqual(chart.name_b, "B: 优化后v2")

    def test_export_images_writes_valid_pngs_with_labels(self):
        if not result_compare.PIL_AVAILABLE:
            self.skipTest("Pillow not installed")
        self._load_and_compare()
        out_dir = self.dir / "charts"
        out_dir.mkdir()
        with mock.patch("result_compare.filedialog.askdirectory",
                        return_value=str(out_dir)):
            self.dialog._export_images()

        files = sorted(out_dir.glob("*.png"))
        self.assertTrue(files)
        for path in files:
            self.assertIn("基线v1", path.name)
            self.assertIn("优化后v2", path.name)
            with open(path, "rb") as handle:
                header = handle.read(8)
            self.assertEqual(header, b"\x89PNG\r\n\x1a\n")

        from PIL import Image
        with Image.open(files[0]) as image:
            self.assertEqual(image.size, (1280, 640))
            self.assertEqual(image.format, "PNG")

    def test_export_images_requires_comparison_first(self):
        with mock.patch("result_compare.showwarning") as warn:
            self.dialog._export_images()
        warn.assert_called_once()

    def test_export_image_status_is_english(self):
        if not result_compare.PIL_AVAILABLE:
            self.skipTest("Pillow not installed")
        i18n.set_language("en")
        try:
            self._load_and_compare()
            out_dir = self.dir / "charts-en"
            out_dir.mkdir()
            with mock.patch("result_compare.filedialog.askdirectory",
                            return_value=str(out_dir)):
                self.dialog._export_images()
            status = self.dialog.compare_status_lbl.cget("text")
            self.assertTrue(status.startswith("Exported "))
        finally:
            i18n.set_language("zh")

    def test_export_csv_default_name_contains_labels(self):
        self._load_and_compare()
        captured = {}

        def fake_save(parent=None, title=None, defaultextension=None,
                      initialfile=None, filetypes=None):
            captured["name"] = initialfile
            return str(self.dir / captured["name"])

        with mock.patch("result_compare.filedialog.asksaveasfilename",
                        side_effect=fake_save):
            self.dialog._export_csv()
        self.assertIn("基线v1", captured["name"])
        self.assertIn("优化后v2", captured["name"])
        self.assertTrue((self.dir / captured["name"]).exists())


class RenderChartPngTests(unittest.TestCase):
    def test_renders_file_without_dialog(self):
        if not result_compare.PIL_AVAILABLE:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chart.png")
            result = render_chart_png(
                path, title="TTFT平均", labels=["4K/1K\nr10k c100", "16K/2K\nr10k c100"],
                values_a=[120.5, 210.8], values_b=[98.4, 180.2],
                name_a="A: 基线v1", name_b="B: 优化后v2",
                unit="ms", decimals=2)
            self.assertEqual(result, path)
            self.assertTrue(os.path.isfile(path))
            from PIL import Image
            with Image.open(path) as image:
                self.assertEqual(image.size, (1280, 640))

    def test_handles_missing_values(self):
        if not result_compare.PIL_AVAILABLE:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chart.png")
            render_chart_png(path, title="QPS", labels=["a", "b"],
                             values_a=[None, 5.0], values_b=[3.0, None],
                             name_a="A", name_b="B")
            self.assertTrue(os.path.isfile(path))

    def test_empty_data_renders_placeholder(self):
        if not result_compare.PIL_AVAILABLE:
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chart.png")
            render_chart_png(path, title="QPS", labels=["a"],
                             values_a=[None], values_b=[None],
                             name_a="A", name_b="B")
            self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
