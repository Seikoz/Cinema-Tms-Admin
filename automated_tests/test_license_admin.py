import hashlib
import json
import runpy
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from license_admin.core import (
    LicenseAuthority,
    canonical_payload,
    extended_license_expiry,
    read_hardware_request,
    trusted_issuer_id,
)
from license_admin.version import __version__


class LicenseAuthorityBootstrapTest(unittest.TestCase):
    def test_admin_project_has_independent_version(self):
        self.assertEqual(__version__, "1.5.0b1")

    def test_vbs_uses_gui_python_with_visible_ime_window_context(self):
        path = Path(__file__).parents[1] / "deployment" / "Cinema-TMS-Admin.vbs"
        self.assertTrue(path.read_bytes().startswith(b"\xff\xfe"))
        source = path.read_text(encoding="utf-16")
        self.assertIn(r'\.python\pythonw.exe', source)
        self.assertIn(r'\.venv\Scripts\pythonw.exe', source)
        self.assertIn("shell.Run(command, 1, True)", source)
        self.assertNotIn("shell.Run(command, 0, True)", source)

    def test_editable_fields_use_native_windows_entry_for_korean_ime(self):
        source = (Path(__file__).parents[1] / "license_admin" / "manager.pyw").read_text(encoding="utf-8")
        native_source = (Path(__file__).parents[1] / "license_admin" / "windows_ime.py").read_text(encoding="utf-8")
        self.assertIn("from license_admin.windows_ime import WindowsImeEntry", source)
        self.assertIn("WindowsImeEntry(master, textvariable=self.variables[key]", source)
        self.assertIn("WindowsImeEntry(issue, textvariable=self.customer", source)
        self.assertIn("WindowsImeEntry(issue, textvariable=self.cinema", source)
        self.assertNotIn("ttk.Entry(issue, textvariable=self.customer", source)
        self.assertNotIn("ttk.Entry(issue, textvariable=self.cinema", source)
        self.assertIn('CreateWindowExW(', native_source)
        self.assertIn('"EDIT"', native_source)
        self.assertIn("WS_TABSTOP", native_source)
        self.assertIn("def _poll_editor(self):", native_source)
        self.assertIn("GetAsyncKeyState(VK_TAB)", native_source)
        self.assertIn("def _focus_relative(self, reverse=False):", native_source)
        self.assertNotIn("SetWindowLongPtrW", native_source)
        self.assertNotIn("WNDPROC", native_source)

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

    def test_latest_license_is_loaded_by_hardware_key(self):
        hardware_key = "3333-3333-3333-3333-3333-3333-3333-3333"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public_pem = self.make_legacy_authority(root)
            with patch("license_admin.core.TRUSTED_PUBLIC_KEY_PEM", public_pem):
                authority = LicenseAuthority(root)
                authority.authenticate("admin", "secret")
                first = authority.issue(
                    customer="첫 고객", cinema="첫 영화관", hardware_key=hardware_key,
                    valid_from=date.today(), expires_on=date.today() + timedelta(days=100),
                    auditorium_limit=2, destination=root / "first.tmslic",
                )
                second = authority.issue(
                    customer="최신 고객", cinema="최신 영화관", hardware_key=hardware_key,
                    valid_from=date.today(), expires_on=date.today() + timedelta(days=365),
                    auditorium_limit=5, destination=root / "second.tmslic",
                    supersedes=first["payload"]["license_id"],
                )
                latest = authority.latest_license_for_hardware_key(hardware_key)
                active = authority.latest_license_for_hardware_key(hardware_key, active_only=True)
        self.assertEqual(latest["license_id"], second["payload"]["license_id"])
        self.assertEqual(active["customer"], "최신 고객")
        self.assertEqual(active["auditorium_limit"], 5)

    def test_hardware_file_load_prefills_existing_license(self):
        source = (Path(__file__).parents[1] / "license_admin" / "manager.pyw").read_text(encoding="utf-8")
        self.assertIn('latest_license_for_hardware_key(request["hardware_key"])', source)
        self.assertIn("def _load_previous_license(self, record: dict", source)
        self.assertIn("기존 사용 이력", source)
        self.assertIn('self.rebind_supersedes = record["license_id"]', source)

    def test_maximum_license_expiry_does_not_overflow(self):
        self.assertEqual(extended_license_expiry(date.max, date(2026, 8, 30)), date.max)
        self.assertEqual(
            extended_license_expiry(date(2027, 8, 30), date(2026, 8, 30)),
            date(2028, 8, 29),
        )

    def test_admin_times_are_displayed_in_utc_plus_nine(self):
        manager = runpy.run_path(
            str(Path(__file__).parents[1] / "license_admin" / "manager.pyw"),
            run_name="license_admin.manager_test",
        )
        self.assertEqual(manager["local_datetime"]("2026-08-30T00:15:00+00:00"), "2026-08-30 09:15")
        source = (Path(__file__).parents[1] / "license_admin" / "manager.pyw").read_text(encoding="utf-8")
        self.assertIn('("time", "시간(UTC+9)", 190)', source)
        self.assertIn('local_datetime(record["created_at"])', source)

    def test_license_history_shows_full_hardware_id_with_scrolling(self):
        source = (Path(__file__).parents[1] / "license_admin" / "manager.pyw").read_text(encoding="utf-8")
        self.assertIn('("hardware", "하드웨어 ID", 285)', source)
        self.assertIn('record["license_id"], record["hardware_key"]', source)
        self.assertIn('orient="horizontal", command=self.tree.xview', source)

    def test_native_entry_uses_tk_font_metrics(self):
        source = (Path(__file__).parents[1] / "license_admin" / "windows_ime.py").read_text(encoding="utf-8")
        self.assertIn('actual_font = font.actual()', source)
        self.assertIn('self._native_font_height', source)
        self.assertNotIn('CreateFontW(-15', source)

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

    def test_online_update_supports_private_github_releases(self):
        source = (Path(__file__).parents[1] / "license_admin" / "manager.pyw").read_text(encoding="utf-8")
        github = (Path(__file__).parents[1] / "license_admin" / "github_updates.py").read_text(encoding="utf-8")
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "publish-update.yml").read_text(encoding="utf-8")
        builder = (Path(__file__).parents[1] / "deployment" / "build-update-package.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('text="온라인 업데이트", command=self.online_update', source)
        self.assertIn('text="GitHub 토큰 설정", command=self.configure_update_token', source)
        self.assertIn('text="파일 업데이트", command=self.install_update', source)
        self.assertIn('check_for_update(APP_VERSION, token)', source)
        self.assertIn('download_update(release, PROJECT_ROOT / "data" / "updates", token)', source)
        self.assertIn('DEFAULT_REPOSITORY = "Seikoz/Cinema-Tms-Admin"', github)
        self.assertIn('CryptProtectData', github)
        self.assertIn('$zip + ".sha256"', builder)
        self.assertIn('gh release upload', workflow)

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
            path = root / relative
            encoding = "utf-16" if path.suffix.lower() == ".vbs" else "utf-8-sig"
            source = path.read_text(encoding=encoding)
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
