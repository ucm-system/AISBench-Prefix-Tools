# -*- coding: utf-8 -*-
"""前缀数量(prefix_num)参数测试"""
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import main
import i18n
from test_designer import TestDesigner


class PrefixNumDesignerTests(unittest.TestCase):
    def _designer_with_case(self):
        designer = TestDesigner()
        designer.set_kv_cache_info(single_kv_cache=1_000_000, dp=2,
                                   max_request_length=8192)
        designer.set_input_lengths([4096])
        designer.set_output_lengths([1024])
        designer.set_repeat_rate(0.8)
        designer.set_request_rate(0)
        designer.generate_test_cases()
        return designer

    def test_prefix_num_defaults_to_request_count(self):
        designer = self._designer_with_case()
        case = designer.test_cases[0]
        self.assertEqual(case.prefix_num, case.data_num_recommended)

    def test_command_uses_case_prefix_num(self):
        designer = self._designer_with_case()
        case = designer.test_cases[0]
        case.prefix_num = 1500
        command = designer.generate_commands()[0]
        self.assertIn(f"--data_num {case.data_num_recommended}", command)
        self.assertIn("--prefix_num 1500", command)

    def test_prefix_num_follows_bulk_request_adjustment(self):
        designer = self._designer_with_case()
        old_data_num = designer.test_cases[0].data_num_recommended
        designer.adjust_data_num(0.5)
        case = designer.test_cases[0]
        self.assertEqual(case.data_num_recommended, old_data_num // 2)
        self.assertEqual(case.prefix_num, case.data_num_recommended)

    def test_custom_prefix_num_is_not_overwritten_by_request_change(self):
        designer = self._designer_with_case()
        case = designer.test_cases[0]
        case.prefix_num = 123
        designer.adjust_single_case(0, data_num=2000)
        self.assertEqual(case.data_num_recommended, 2000)
        self.assertEqual(case.prefix_num, 123)

    def test_single_case_prefix_num_can_be_set(self):
        designer = self._designer_with_case()
        designer.adjust_single_case(0, prefix_num=777)
        self.assertEqual(designer.test_cases[0].prefix_num, 777)

    def test_duplicate_case_copies_prefix_num(self):
        designer = self._designer_with_case()
        designer.test_cases[0].prefix_num = 555
        self.assertTrue(designer.duplicate_case(0))
        self.assertEqual(designer.test_cases[-1].prefix_num, 555)

    def test_custom_case_prefix_num_defaults_to_request_count(self):
        designer = self._designer_with_case()
        designer.add_custom_case(2048, 512, data_num=1000)
        case = designer.test_cases[-1]
        self.assertEqual(case.prefix_num, 1000)

        designer.add_custom_case(2048, 512, data_num=1000, prefix_num=300)
        self.assertEqual(designer.test_cases[-1].prefix_num, 300)


class PrefixNumGuiTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("zh")

    def tearDown(self):
        i18n.set_language("zh")

    def _app_with_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path",
                            return_value=settings_file):
                app = main.WizardApp()
        try:
            app.current_step = 3
            app._show_step(3)
            app.designer.set_kv_cache_info(1_000_000, 2, 8192)
            app.designer.set_input_lengths([4096])
            app.designer.set_output_lengths([1024])
            app.designer.set_repeat_rate(0.8)
            app.designer.set_request_rate(0)
            app.designer.generate_test_cases()
            app._refresh_test_tree()
            app.root.update_idletasks()
            app.root.update()
            return app
        except Exception:
            app.root.destroy()
            raise

    def test_table_shows_editable_prefix_num_column(self):
        app = self._app_with_cases()
        try:
            self.assertEqual(app.test_tree.heading("prefix_num")["text"],
                             "前缀数量(prefix_num)")
            self.assertEqual(main.WizardApp.TEST_TREE_EDITABLE_FIELDS["#5"],
                             "prefix_num")

            first = app.test_tree.get_children()[0]
            values = app.test_tree.item(first)["values"]
            case = app.designer.test_cases[0]
            self.assertEqual(str(values[4]), f"{case.prefix_num:,}")

            command = app.designer.generate_commands()[0]
            self.assertIn(f"--prefix_num {case.prefix_num}", command)
        finally:
            app.root.destroy()

    def test_inline_prefix_num_editor_and_apply(self):
        app = self._app_with_cases()
        try:
            first = app.test_tree.get_children()[0]
            bbox = app.test_tree.bbox(first, "#5")
            self.assertTrue(bbox, "prefix_num cell is not visible for editing")
            x, y, _width, _height = bbox

            with mock.patch("main.showwarning") as warn:
                app._on_tree_edit(SimpleNamespace(x=x, y=y))
                app.root.update_idletasks()

                entries = [w for w in app.test_tree.winfo_children()
                           if isinstance(w, main.tk.Entry)]
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0].get(),
                                 str(app.designer.test_cases[0].prefix_num))

            # 模拟用户输入4321并确认
            app._apply_tree_edit(app.designer.test_cases[0],
                                 "prefix_num", 4321)
            self.assertEqual(app.designer.test_cases[0].prefix_num, 4321)

            # 修改请求数时, 前缀数量默认同步; 单独修改过则保持用户值
            app._apply_tree_edit(app.designer.test_cases[0],
                                 "data_num_recommended", 2000)
            self.assertEqual(app.designer.test_cases[0].prefix_num, 4321)
            warn.assert_not_called()
        finally:
            app.root.destroy()

    def test_language_switch_keeps_prefix_num_values(self):
        app = self._app_with_cases()
        try:
            case = app.designer.test_cases[0]
            case.prefix_num = 8888
            app._refresh_test_tree()

            with tempfile.TemporaryDirectory() as tmp:
                settings_file = Path(tmp) / "settings.json"
                with mock.patch("settings_manager.settings_path",
                                return_value=settings_file):
                    app.language_var.set("English")
                    app._on_language_change()

            self.assertEqual(app.test_tree.heading("prefix_num")["text"],
                             "Prefix count (prefix_num)")
            first = app.test_tree.get_children()[0]
            values = app.test_tree.item(first)["values"]
            self.assertEqual(str(values[4]), "8,888")
            self.assertIn("--prefix_num 8888",
                          app.designer.generate_commands()[0])
        finally:
            i18n.set_language("zh")
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
