"""Exercise updater UI transitions without opening the operational database."""
import importlib.util
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class UpdateProgressTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "license_admin" / "manager.pyw"
        loader = SourceFileLoader("update_progress_manager", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.module = importlib.util.module_from_spec(spec)
        previous_hook = sys.excepthook
        try:
            loader.exec_module(cls.module)
        finally:
            sys.excepthook = previous_hook
        cls.manager = cls.module.LicenseManager

    def test_download_percentage_uses_actual_bytes(self):
        host = Mock()
        self.manager.update_online_download_progress(host, "1.7.0b2", 1024**2, 4 * 1024**2)
        message, percent = host.set_online_update_progress.call_args.args
        self.assertEqual(percent, 25)
        self.assertIn("1.0 / 4.0 MB", message)

    def test_indeterminate_then_download_progress(self):
        host = Mock()
        self.manager.set_online_update_progress(host, "확인 중")
        host.online_progress_bar.configure.assert_called_with(mode="indeterminate")
        host.online_progress_bar.start.assert_called_once()
        self.manager.set_online_update_progress(host, "다운로드", 25)
        host.online_progress_bar.configure.assert_called_with(mode="determinate")
        host.online_progress_value.set.assert_called_with(25)
        host.online_progress_percent.set.assert_called_with("다운로드 25%")

    def test_no_update_and_declined_install_restore_ui(self):
        for release in (None, SimpleNamespace(version="1.7.0b2", published_at="")):
            with self.subTest(release=release), patch.object(self.module.messagebox, "showinfo"), patch.object(self.module.messagebox, "askyesno", return_value=False):
                host = Mock()
                self.manager.confirm_online_update(host, release, "test-token")
                host.close_online_update_progress.assert_called_once()
                host._refresh_permissions.assert_called_once()

    def test_download_disk_error_is_reported_on_ui_thread(self):
        host = Mock()
        host.after.side_effect = lambda delay, callback: callback()
        with patch.object(self.module, "download_update", side_effect=OSError("disk full")):
            self.manager.online_update_download_worker(host, Mock(), "test-token")
        host.finish_online_update_error.assert_called_once_with("disk full")

    def test_launch_failure_preserves_login(self):
        host = Mock()
        with patch.object(Path, "is_file", return_value=True), patch.object(self.module.subprocess, "Popen", side_effect=OSError("launch failed")):
            self.manager.launch_update_package(host, Path("update.zip"))
        host.authority.logout.assert_not_called()
        host.destroy.assert_not_called()
        host.finish_online_update_error.assert_called_once()

    def test_error_closes_popup_and_restores_permissions(self):
        host = Mock()
        with patch.object(self.module.messagebox, "showerror") as error:
            self.manager.finish_online_update_error(host, "failure")
        host.close_online_update_progress.assert_called_once()
        host._refresh_permissions.assert_called_once()
        error.assert_called_once_with("온라인 업데이트", "failure", parent=host)
