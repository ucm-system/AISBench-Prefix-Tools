import tkinter as tk
import unittest
from unittest import mock

import log_tools


class KVCacheGrepTests(unittest.TestCase):
    """KV cache 筛选命令使用通用关键词, 兼容 GPU/NPU 等不同生态"""

    def test_builtin_grep_command_uses_generic_kv_cache_keyword(self):
        self.assertIn("KV cache size", log_tools.KV_GREP_COMMAND)
        self.assertNotIn("GPU KV cache size", log_tools.KV_GREP_COMMAND)
        self.assertIn("Maximum concurrency", log_tools.KV_GREP_COMMAND)

    def test_parse_accepts_gpu_npu_and_unprefixed_kv_cache_lines(self):
        parse = log_tools.RemoteLogBrowser._parse_kv_results

        kv, max_len = parse(
            "GPU KV cache size: 198469 tokens\n"
            "Maximum concurrency for 131072 tokens per request: 2.0x")
        self.assertEqual((kv, max_len), (198469, 131072))

        kv, max_len = parse(
            "NPU KV cache size: 123,456 tokens\n"
            "Maximum concurrency for 65,536 tokens per request: 3.0x")
        self.assertEqual((kv, max_len), (123456, 65536))

        kv, max_len = parse(
            "KV cache size: 100000 tokens\n"
            "Maximum concurrency for 8192 tokens per request: 1.0x")
        self.assertEqual((kv, max_len), (100000, 8192))

    def test_parse_returns_none_when_no_match(self):
        parse = log_tools.RemoteLogBrowser._parse_kv_results
        self.assertEqual(parse("no cache info here"), (None, None))


class GrepCommandTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self._dialogs = []

    def tearDown(self):
        for dialog in self._dialogs:
            try:
                dialog.destroy()
            except tk.TclError:
                pass
        self.root.destroy()

    def _browser(self):
        ssh = mock.Mock()
        ssh.connected = False
        browser = log_tools.RemoteLogBrowser(
            self.root, ssh,
            kv_cache_var=tk.StringVar(),
            max_req_len_var=tk.StringVar())
        self._dialogs.append(browser.dialog)
        return browser

    def test_grep_command_uses_generic_kv_cache_keyword(self):
        browser = self._browser()
        browser.source_var.set("host")
        browser.current_file = "/var/log/vllm_serve.log"

        cmd = browser._grep_command()

        self.assertIn("grep -e 'KV cache size' -e 'Maximum concurrency'", cmd)
        self.assertNotIn("GPU KV cache size", cmd)
        self.assertIn("/var/log/vllm_serve.log", cmd)

    def test_docker_logs_mode_wraps_grep_command(self):
        browser = self._browser()
        browser.source_var.set("docker_logs")
        browser.container_var.set("aisbench-test-0101")

        cmd = browser._grep_command()

        self.assertIn("docker logs aisbench-test-0101", cmd)
        self.assertIn("KV cache size", cmd)


if __name__ == "__main__":
    unittest.main()
