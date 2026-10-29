import unittest
from unittest import mock

import main
from docker_manager import DockerManager


class WizardFlowTests(unittest.TestCase):
    def test_docker_and_file_steps_are_merged(self):
        self.assertEqual(
            main.WizardApp.STEP_TITLES,
            ["SSH连接", "Docker部署", "配置文件", "测试用例", "执行测试"],
        )

    def test_residual_container_cleanup_is_supported(self):
        self.assertTrue(hasattr(main.WizardApp, "_open_residual_container_dialog"))
        self.assertTrue(hasattr(main.WizardApp, "_start_residual_scan"))

    def test_container_workspace_is_not_host_mounted(self):
        import inspect

        signature = inspect.signature(main.DockerManager.create_container)
        self.assertNotIn("code_host_path", signature.parameters)
        self.assertIn("org.aisbench-prefix-tools.managed=true",
                      main.DockerManager.MANAGED_LABEL)


class FakeDeploySSH:
    """模拟执行机: 记录命令并模拟docker/文件系统行为"""

    connected = True

    class _SFTP:
        @staticmethod
        def get(remote, local):
            with open(local, "wb") as f:
                f.write(b"fake")

    sftp = _SFTP()

    def __init__(self):
        self.commands = []
        self.dirs = set()

    def execute(self, command, timeout=300):
        self.commands.append(command)
        if command.startswith("docker --version"):
            return 0, "Docker version 27.3.1", ""
        if command.startswith("docker ps -a --filter"):
            return 0, "", ""
        if command.startswith("docker ps --filter"):
            return 0, "Up 2 seconds", ""
        if "docker images" in command:
            return 0, "aisbench:v3.1", ""
        if command.startswith("docker exec"):
            if " ls " in command:
                return 0, "run.py\nconfig.py", ""
            if " test -d " in command or " test -e " in command:
                return 0, "", ""
            return 0, "", ""
        if command.startswith("rm -rf "):
            self.dirs.discard(command[len("rm -rf "):])
            return 0, "", ""
        if command.startswith("mkdir -p "):
            self.dirs.add(command[len("mkdir -p "):])
            return 0, "", ""
        if command.startswith("ls "):
            return 0, "", ""
        return 0, "", ""

    def execute_with_callback(self, command, callback=None, timeout=300):
        self.commands.append(command)
        if callback:
            callback("ok\n")
        return 0

    def mkdir_p(self, path):
        self.dirs.add(path)
        self.commands.append(f"mkdir -p {path}")

    def file_exists(self, path):
        return path in self.dirs

    def upload_file(self, local_path, remote_path, progress=None):
        return True


class DeploySequenceTests(unittest.TestCase):
    def test_deploy_imports_code_into_container_and_removes_staging_dir(self):
        app = main.WizardApp()
        try:
            ssh = FakeDeploySSH()
            app.ssh = ssh
            app.docker = DockerManager(ssh)
            app.image_source_var.set("existing")
            app.remote_image_var.set("aisbench:v3.1")
            app.code_source_var.set("builtin")
            app.model_path_var.set("/mnt/models/ds")
            app.work_dir_var.set("/tmp/AISBench_Prefix_Tools")

            with mock.patch("main.messagebox.showinfo"):
                app._deploy_sequence(
                    "/mnt/models/ds", "", "aisbench:v3.1"
                )
                app._docker_log_handler.finalize()
                app.root.update()

            run_cmd = next(
                c for c in ssh.commands if c.startswith("docker run"))
            self.assertIn("--label org.aisbench-prefix-tools.managed=true", run_cmd)
            self.assertNotIn("aisbench_auto_tools_prefix-main", run_cmd)

            cp_cmd = next(
                c for c in ssh.commands if c.startswith("docker cp"))
            self.assertIn("docker cp /tmp/AISBench_Prefix_Tools/"
                          "aisbench_auto_tools_prefix-main/.", cp_cmd)
            self.assertIn(":/benchmark/ais_bench/"
                          "aisbench_auto_tools_prefix-main", cp_cmd)

            self.assertIn("rm -rf /tmp/AISBench_Prefix_Tools", ssh.commands)
            self.assertNotIn("/tmp/AISBench_Prefix_Tools", ssh.dirs)
            self.assertTrue(app.docker.container_name.startswith("aisbench-test-"))
            self.assertIsNotNone(app.config_mgr)
        finally:
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
