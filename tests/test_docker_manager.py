import json
import unittest

from docker_manager import DockerManager


class FakeSSHManager:
    def __init__(self, output="", exit_code=0, error=""):
        self.output = output
        self.exit_code = exit_code
        self.error = error
        self.commands = []

    def execute(self, command, timeout=300):
        self.commands.append(command)
        return self.exit_code, self.output, self.error


class DockerManagerImageListTests(unittest.TestCase):
    def test_list_images_parses_named_images(self):
        payload = "\n".join([
            json.dumps({
                "Repository": "aisbench",
                "Tag": "v3.1",
                "ID": "abc123def456",
                "CreatedSince": "2 days ago",
                "Size": "12.3GB",
            }),
            json.dumps({
                "Repository": "<none>",
                "Tag": "<none>",
                "ID": "dangling",
                "CreatedSince": "1 day ago",
                "Size": "1.2GB",
            }),
        ])
        ssh = FakeSSHManager(payload)
        manager = DockerManager(ssh)

        images = manager.list_images()

        self.assertIn("docker image ls --format '{{json .}}'", ssh.commands[0])
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["name"], "aisbench:v3.1")
        self.assertEqual(images[0]["id"], "abc123def456")
        self.assertEqual(images[0]["created"], "2 days ago")
        self.assertEqual(images[0]["size"], "12.3GB")

    def test_list_images_reports_docker_failure(self):
        ssh = FakeSSHManager(error="Cannot connect to the Docker daemon", exit_code=1)
        manager = DockerManager(ssh)

        with self.assertRaisesRegex(RuntimeError, "Cannot connect"):
            manager.list_images()


if __name__ == "__main__":
    unittest.main()
