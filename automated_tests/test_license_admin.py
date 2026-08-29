import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from license_admin.core import LicenseAuthority, canonical_payload, read_hardware_request, trusted_issuer_id
from license_admin.version import __version__


class LicenseAuthorityBootstrapTest(unittest.TestCase):
    def test_admin_project_has_independent_version(self):
        self.assertEqual(__version__, "1.3.0b1")

    def test_hardware_rebind_request_preserves_previous_key(self):
        request = {
            "schema": 1,
            "product": "cinema-tms",
            "request_id": "rebind-test",
            "hardware_key": "2222-2222-2222-2222-2222-2222-2222-2222",
            "issuer_id": trusted_issuer_id(),
            "created_at": "2026-08-25T00:00:00+09:00",
            "request_type": "hardware_rebind",
            "previous_hardware_key": "1111-1111-1111-1111-1111-1111-1111-1111",
        }
        request["checksum"] = hashlib.sha256(canonical_payload(request)).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rebind.tmshw"
            path.write_text(json.dumps(request), encoding="utf-8")
            loaded = read_hardware_request(path)
        self.assertEqual(loaded["request_type"], "hardware_rebind")
        self.assertEqual(loaded["previous_hardware_key"], request["previous_hardware_key"])

    def test_offline_update_support_is_independent_and_preserves_data(self):
        root = Path(__file__).parents[1]
        apply_source = (root / "deployment" / "apply-update.ps1").read_text(encoding="utf-8-sig")
        build_source = (root / "deployment" / "build-update-package.ps1").read_text(encoding="utf-8-sig")
        manager_source = (root / "license_admin" / "manager.pyw").read_text(encoding="utf-8")
        self.assertIn('$productId = "cinema-tms-admin"', apply_source)
        self.assertIn("update-backups", apply_source)
        self.assertIn("BaselineManifestPath", build_source)
        self.assertIn("def install_update", manager_source)
        self.assertIn("관리자 계정, 발급키, 라이선스 이력 DB는 그대로 유지", manager_source)

    def test_default_database_is_inside_admin_project(self):
        from license_admin.core import DEFAULT_DATA_DIR

        self.assertEqual(DEFAULT_DATA_DIR, Path(__file__).parents[1] / "data")

    def test_admin_runtime_does_not_reference_client_project(self):
        root = Path(__file__).parents[1]
        for relative in (
            "deployment/Cinema-TMS-Admin.vbs",
            "deployment/Cinema-TMS-Admin.cmd",
            "deployment/build-admin-package.ps1",
        ):
            source = (root / relative).read_text(encoding="utf-8-sig")
            self.assertNotIn("Cinema_Tms\\.python", source)

    def make_legacy_authority(self, root: Path, username: str = "admin", password: str = "secret"):
        private_key = Ed25519PrivateKey.generate()
        public_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        root.mkdir(parents=True, exist_ok=True)
        (root / "license_private_key.pem").write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        with patch("license_admin.core.TRUSTED_PUBLIC_KEY_PEM", public_pem):
            authority = LicenseAuthority(root)
            authority.bootstrap_admin(username, password)
        return public_pem

    def test_clean_database_explains_that_an_existing_authority_is_required(self):
        with tempfile.TemporaryDirectory() as folder:
            authority = LicenseAuthority(Path(folder))
            with self.assertRaisesRegex(ValueError, "licenses.db"):
                authority.bootstrap_admin("admin", "secret")

    def test_imports_existing_database_and_authenticates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public_pem = self.make_legacy_authority(root / "source")
            target = LicenseAuthority(root / "target")

            target.import_database(root / "source" / "licenses.db")

            with patch("license_admin.core.TRUSTED_PUBLIC_KEY_PEM", public_pem):
                user = target.authenticate("admin", "secret")
            self.assertEqual(user.role, "admin")
            self.assertTrue(target.unlocked)

    def test_rejects_an_empty_database_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            empty = LicenseAuthority(root / "empty")
            target = LicenseAuthority(root / "target")

            with self.assertRaisesRegex(ValueError, "활성 관리자"):
                target.import_database(empty.database_path)


if __name__ == "__main__":
    unittest.main()
