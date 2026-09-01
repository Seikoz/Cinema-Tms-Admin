import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from license_admin.github_updates import (
    GitHubUpdateError, ReleaseAsset, UpdateRelease, download_update,
    load_update_token, parse_update_releases, save_update_token, version_key,
)


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0

    def read(self, size=-1):
        if size < 0:
            size = len(self.payload) - self.offset
        result = self.payload[self.offset:self.offset + size]
        self.offset += len(result)
        return result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class GitHubUpdatesTest(unittest.TestCase):
    def test_version_order(self):
        self.assertLess(version_key("1.5.0b1"), version_key("1.5.0"))
        self.assertGreater(version_key("1.6.0b1"), version_key("1.5.9"))

    def test_release_requires_package_and_checksum(self):
        assets = [
            {"name": "Cinema-TMS-Admin-Update-1.5.0b2.zip", "url": "https://api.github.com/assets/1", "size": 20},
            {"name": "Cinema-TMS-Admin-Update-1.5.0b2.zip.sha256", "url": "https://api.github.com/assets/2", "size": 80},
        ]
        payload = [{"tag_name": "v1.5.0b2", "draft": False, "assets": assets}]
        self.assertEqual(parse_update_releases(payload, "1.5.0b1").version, "1.5.0b2")
        self.assertIsNone(parse_update_releases(payload, "1.5.0b2"))
        assets.pop()
        self.assertIsNone(parse_update_releases(payload, "1.5.0b1"))

    def test_token_is_not_saved_as_plain_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token.dpapi"
            save_update_token(path, "secret-token", protector=lambda value: b"sealed" + value[::-1])
            self.assertNotIn(b"secret-token", path.read_bytes())
            self.assertEqual(load_update_token(path, unprotector=lambda value: value.removeprefix(b"sealed")[::-1]), "secret-token")

    def test_download_verifies_hash_and_size(self):
        package = b"admin-update"
        checksum = hashlib.sha256(package).hexdigest().encode("ascii")
        release = UpdateRelease(
            "1.5.0b2", "",
            ReleaseAsset("Cinema-TMS-Admin-Update-1.5.0b2.zip", "https://api.github.com/assets/1", len(package)),
            ReleaseAsset("Cinema-TMS-Admin-Update-1.5.0b2.zip.sha256", "https://api.github.com/assets/2", len(checksum)),
        )
        with tempfile.TemporaryDirectory() as folder:
            with patch("license_admin.github_updates._open", side_effect=[Response(checksum), Response(package)]):
                target = download_update(release, Path(folder), "token")
            self.assertEqual(target.read_bytes(), package)

    def test_download_rejects_bad_hash(self):
        package = b"tampered"
        release = UpdateRelease(
            "1.5.0b2", "",
            ReleaseAsset("Cinema-TMS-Admin-Update-1.5.0b2.zip", "https://api.github.com/assets/1", len(package)),
            ReleaseAsset("Cinema-TMS-Admin-Update-1.5.0b2.zip.sha256", "https://api.github.com/assets/2", 64),
        )
        with tempfile.TemporaryDirectory() as folder:
            with patch("license_admin.github_updates._open", side_effect=[Response(b"0" * 64), Response(package)]):
                with self.assertRaises(GitHubUpdateError):
                    download_update(release, Path(folder), "token")


if __name__ == "__main__":
    unittest.main()
