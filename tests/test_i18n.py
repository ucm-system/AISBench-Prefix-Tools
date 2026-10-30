import tempfile
import unittest
import tkinter as tk
from pathlib import Path
from unittest import mock

import i18n
import main
from log_tools import RemoteLogBrowser
from result_compare import ResultCompareDialog
from settings_manager import load_settings


class I18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("zh")

    def test_supported_languages(self):
        self.assertEqual(i18n.SUPPORTED_LANGUAGES, {"zh": "中文", "en": "English"})

    def test_translate_static_text(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("SSH连接"), "SSH Connection")
        self.assertEqual(i18n.tr("Docker部署"), "Docker Deployment")

    def test_unknown_text_falls_back_to_source(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("不存在的界面文本"), "不存在的界面文本")

    def test_chinese_language_returns_source(self):
        i18n.set_language("zh")
        self.assertEqual(i18n.tr("SSH连接"), "SSH连接")

    def test_invalid_language_falls_back_to_chinese(self):
        i18n.set_language("fr")
        self.assertEqual(i18n.get_language(), "zh")


class LanguageSwitchTests(unittest.TestCase):
    def test_language_switch_rebuilds_ui_and_persists_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            with mock.patch("settings_manager.settings_path", return_value=settings_file):
                app = main.WizardApp()
                try:
                    self.assertEqual(app.language_var.get(), "中文")
                    self.assertEqual(app.step_buttons[0][1].cget("text"), "1. SSH连接")

                    app.language_var.set("English")
                    app._on_language_change()

                    self.assertEqual(i18n.get_language(), "en")
                    self.assertEqual(app.step_buttons[0][1].cget("text"), "1. SSH Connection")
                    self.assertEqual(app.prev_btn.cget("text"), "< Previous")
                    self.assertEqual(app.next_btn.cget("text"), "Next >")
                    self.assertEqual(app.language_var.get(), "English")
                    self.assertEqual(load_settings().get("language"), "en")
                finally:
                    app.root.destroy()

    def test_result_compare_dialog_uses_localized_labels(self):
        root = tk.Tk()
        try:
            i18n.set_language("en")
            dialog = ResultCompareDialog(root)
            texts = []

            def walk(widget):
                for child in widget.winfo_children():
                    try:
                        text = child.cget("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text)
                    except Exception:
                        pass
                    walk(child)

            walk(dialog.dialog)
            self.assertIn("File A (baseline):", texts)
            self.assertIn("Select CSV...", texts)
        finally:
            root.destroy()

    def test_remote_log_browser_uses_localized_labels(self):
        root = tk.Tk()

        class FakeSSH:
            connected = False

        try:
            i18n.set_language("en")
            browser = RemoteLogBrowser(root, FakeSSH())
            texts = []

            def walk(widget):
                for child in widget.winfo_children():
                    try:
                        text = child.cget("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text)
                    except Exception:
                        pass
                    walk(child)

            walk(browser.dialog)
            self.assertIn("Other server", texts)
            self.assertIn("Filter KV cache", texts)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
