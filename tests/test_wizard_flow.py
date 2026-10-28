import unittest

import main


class WizardFlowTests(unittest.TestCase):
    def test_docker_and_file_steps_are_merged(self):
        self.assertEqual(
            main.WizardApp.STEP_TITLES,
            ["SSH连接", "Docker部署", "配置文件", "测试用例", "执行测试"],
        )


if __name__ == "__main__":
    unittest.main()
