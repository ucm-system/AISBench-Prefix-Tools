import unittest

from log_tools import KV_GREP_COMMAND, RemoteLogBrowser


class KVCacheKeywordCompatibilityTests(unittest.TestCase):
    """GPU/NPU KV cache size 两种日志关键词均需可查询并解析"""

    def test_grep_command_matches_both_gpu_and_npu_keywords(self):
        self.assertIn("-e 'GPU KV cache size'", KV_GREP_COMMAND)
        self.assertIn("-e 'NPU KV cache size'", KV_GREP_COMMAND)
        self.assertIn("-e 'Maximum concurrency'", KV_GREP_COMMAND)

    def test_parse_gpu_kv_cache_size(self):
        kv, max_len = RemoteLogBrowser._parse_kv_results(
            "INFO: GPU KV cache size: 198,469 tokens\n"
            "INFO: Maximum concurrency for 131,072 tokens per request")
        self.assertEqual(kv, 198469)
        self.assertEqual(max_len, 131072)

    def test_parse_npu_kv_cache_size(self):
        kv, max_len = RemoteLogBrowser._parse_kv_results(
            "INFO: NPU KV cache size: 198,469 tokens\n"
            "INFO: Maximum concurrency for 131,072 tokens per request")
        self.assertEqual(kv, 198469)
        self.assertEqual(max_len, 131072)

    def test_gpu_and_npu_lines_coexist(self):
        # 同一份日志中两种关键词共存时也能解析出KV cache值
        kv, max_len = RemoteLogBrowser._parse_kv_results(
            "INFO: GPU KV cache size: 123,456 tokens\n"
            "INFO: NPU KV cache size: 198,469 tokens\n"
            "INFO: Maximum concurrency for 131,072 tokens per request")
        self.assertIsNotNone(kv)
        self.assertEqual(max_len, 131072)

    def test_unrelated_lines_are_ignored(self):
        kv, max_len = RemoteLogBrowser._parse_kv_results(
            "INFO: no cache lines here\nINFO: something else")
        self.assertIsNone(kv)
        self.assertIsNone(max_len)


if __name__ == "__main__":
    unittest.main()
