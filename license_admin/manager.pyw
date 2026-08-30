"""Login-protected GUI for issuing machine-bound Cinema TMS licenses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from license_admin.version import __version__ as APP_VERSION
from license_admin.core import LegacyKeyMigrationRequired, LicenseAuthority, extended_license_expiry, read_hardware_request
from license_admin.windows_ime import WindowsImeEntry


ROLE_LABELS = {"admin": "관리자", "operator": "발급 담당자", "viewer": "조회 전용"}
ACTION_LABELS = {"issue": "신규 발급", "renewal": "갱신"}
LICENSE_STATUS_LABELS = {"active": "활성", "renewed": "갱신됨", "revoked": "폐기"}
ERROR_LOG_PATH = PROJECT_ROOT / "data" / "admin-error.log"
UPDATE_RESULT_PATH = PROJECT_ROOT / "data" / "last-update-result.json"
KST = timezone(timedelta(hours=9))


def report_python_error(exc_type, exc_value, exc_traceback) -> None:
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG_PATH.open("a", encoding="utf-8") as log:
            log.write(f"\n[{datetime.now(KST).isoformat()}]\n{detail}")
    except OSError:
        pass
    try:
        messagebox.showerror(
            "Cinema TMS Admin Python 오류",
            f"프로그램 실행 중 오류가 발생했습니다.\n{exc_value}\n\n오류 로그: {ERROR_LOG_PATH}",
        )
    except tk.TclError:
        pass


sys.excepthook = report_python_error


def local_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return value or "-"


def configure_windows_korean_text(root: tk.Misc) -> None:
    """Use a Unicode Korean UI font while leaving composition to Windows IME."""
    if os.name != "nt":
        return
    for name in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont"):
        try:
            tkfont.nametofont(name, root=root).configure(family="Malgun Gothic")
        except tk.TclError:
            continue


class FormDialog(simpledialog.Dialog):
    def __init__(self, parent, title, fields, *, note=""):
        self.fields = fields
        self.note = note
        self.variables = {key: tk.StringVar(value=default) for key, _label, _secret, default in fields}
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        if self.note:
            ttk.Label(master, text=self.note, wraplength=430, justify="left").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
            )
        first = None
        start = 1 if self.note else 0
        for offset, (key, label, secret, _default) in enumerate(self.fields):
            ttk.Label(master, text=label).grid(row=start + offset, column=0, sticky="w", padx=(0, 12), pady=5)
            entry = WindowsImeEntry(master, textvariable=self.variables[key], width=34, show="●" if secret else "")
            entry.grid(row=start + offset, column=1, sticky="ew", pady=5)
            if first is None:
                first = entry
        master.columnconfigure(1, weight=1)
        return first

    def apply(self):
        self.result = {key: variable.get() for key, variable in self.variables.items()}


class LicenseManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.authority = LicenseAuthority()
        self.title(f"Cinema TMS {APP_VERSION} 라이선스 관리")
        self.geometry("1380x760")
        self.minsize(1100, 680)
        self.customer = tk.StringVar()
        self.cinema = tk.StringVar()
        self.hardware_key = tk.StringVar()
        self.hardware_source = tk.StringVar(value="하드웨어 키 파일을 불러오세요.")
        self.valid_from = tk.StringVar(value=date.today().isoformat())
        self.expires_on = tk.StringVar(value=(date.today() + timedelta(days=365)).isoformat())
        self.auditorium_limit = tk.StringVar(value="1")
        self.status = tk.StringVar(value="로그인이 필요합니다.")
        self.request_loaded = False
        self.rebind_supersedes = ""
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close_application)
        self.withdraw()
        self.after(100, self.start_authentication)

    def report_callback_exception(self, exc_type, exc_value, exc_traceback):
        report_python_error(exc_type, exc_value, exc_traceback)

    def _build(self):
        configure_windows_korean_text(self)
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=27)
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)

        authority = ttk.LabelFrame(root, text="로그인 계정 보안", padding=12)
        authority.pack(fill="x")
        ttk.Label(authority, text="발급 권한은 암호화된 관리자 DB와 로그인 계정으로 관리됩니다.").pack(side="left")
        self.logout_button = ttk.Button(authority, text="로그아웃", command=self.logout)
        self.logout_button.pack(side="right")
        self.update_button = ttk.Button(authority, text="프로그램 업데이트", command=self.install_update)
        self.update_button.pack(side="right", padx=6)
        self.password_button = ttk.Button(authority, text="비밀번호 변경", command=self.change_password)
        self.password_button.pack(side="right", padx=6)
        self.audit_button = ttk.Button(authority, text="감사 로그", command=self.show_audit)
        self.audit_button.pack(side="right", padx=6)
        self.accounts_button = ttk.Button(authority, text="계정 관리", command=self.manage_accounts)
        self.accounts_button.pack(side="right", padx=6)
        ttk.Label(authority, textvariable=self.status).pack(side="right", padx=14)

        issue = ttk.LabelFrame(root, text="라이선스 발급", padding=12)
        issue.pack(fill="x", pady=14)
        ttk.Label(issue, text="고객명").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(issue, text="영화관명").grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Label(issue, text="사용 기간").grid(row=0, column=2, sticky="w")
        ttk.Label(issue, text="허용 상영관 수").grid(row=0, column=3, sticky="w", padx=(12, 0))
        WindowsImeEntry(issue, textvariable=self.customer, width=26).grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(3, 10))
        WindowsImeEntry(issue, textvariable=self.cinema, width=26).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(3, 10))
        dates = ttk.Frame(issue)
        dates.grid(row=1, column=2, sticky="ew", pady=(3, 10))
        WindowsImeEntry(dates, textvariable=self.valid_from, width=12).pack(side="left")
        ttk.Label(dates, text=" ~ ").pack(side="left")
        WindowsImeEntry(dates, textvariable=self.expires_on, width=12).pack(side="left")
        ttk.Spinbox(issue, textvariable=self.auditorium_limit, from_=1, to=9999, width=12).grid(
            row=1, column=3, sticky="ew", padx=(12, 0), pady=(3, 10)
        )

        ttk.Label(issue, text="클라이언트 하드웨어 키 파일").grid(row=2, column=0, sticky="w", padx=(0, 12))
        hardware = ttk.Frame(issue)
        hardware.grid(row=3, column=0, columnspan=4, sticky="ew")
        ttk.Entry(hardware, textvariable=self.hardware_key, state="readonly", width=42).pack(side="left", fill="x", expand=True)
        self.load_button = ttk.Button(hardware, text=".tmshw 파일 불러오기", command=self.load_hardware_file)
        self.load_button.pack(side="left", padx=8)
        ttk.Label(hardware, textvariable=self.hardware_source).pack(side="left", padx=(4, 12))
        self.issue_button = ttk.Button(hardware, text="라이선스 파일 발급", command=self.issue, state="disabled")
        self.issue_button.pack(side="right")
        for column in range(4):
            issue.columnconfigure(column, weight=1)

        history = ttk.LabelFrame(root, text="발급 이력", padding=10)
        history.pack(fill="both", expand=True)
        columns = ("id", "hardware", "customer", "cinema", "limit", "action", "operator", "processed", "expires", "status")
        table = ttk.Frame(history)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        headings = (
            ("id", "라이선스 ID", 255), ("hardware", "하드웨어 ID", 285),
            ("customer", "고객", 95), ("cinema", "영화관", 95),
            ("limit", "상영관 한도", 85), ("action", "처리 구분", 75),
            ("operator", "담당자", 95), ("processed", "처리 일시", 145),
            ("expires", "만료일", 90), ("status", "상태", 75),
        )
        for key_name, label, width in headings:
            self.tree.heading(key_name, text=label)
            self.tree.column(key_name, width=width, minwidth=width, anchor="w", stretch=key_name not in {"id", "hardware"})
        vertical_scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        horizontal_scroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical_scroll.set, xscrollcommand=horizontal_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        actions = ttk.Frame(history)
        actions.pack(fill="x", pady=(10, 0))
        self.renew_button = ttk.Button(actions, text="선택 항목 갱신", command=self.prepare_renewal)
        self.renew_button.pack(side="left")
        self.revoke_button = ttk.Button(actions, text="선택 항목 폐기 표시", command=self.revoke)
        self.revoke_button.pack(side="left", padx=8)
        ttk.Button(actions, text="새로고침", command=self.refresh_records).pack(side="right")

    def start_authentication(self):
        self.deiconify()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))
        if not self.authority.has_users:
            setup_ok = self.setup_first_admin() if self.authority.requires_migration else self.import_existing_authority()
            if not setup_ok:
                self.destroy()
                return
        if not self.login():
            self.destroy()
            return
        self.refresh_records()
        self._refresh_permissions()
        self.after(250, self.show_update_result)

    def show_update_result(self):
        if not UPDATE_RESULT_PATH.is_file():
            return
        try:
            result = json.loads(UPDATE_RESULT_PATH.read_text(encoding="utf-8-sig"))
            UPDATE_RESULT_PATH.unlink(missing_ok=True)
        except (OSError, ValueError):
            return
        if result.get("success"):
            version = result.get("version") or "새 버전"
            messagebox.showinfo("라이선스 관리자 업데이트", f"Cinema TMS Admin {version} 업데이트를 완료했습니다.\n계정, 발급키와 라이선스 이력은 유지되었습니다.", parent=self)
        else:
            messagebox.showerror("라이선스 관리자 업데이트", f"업데이트에 실패했습니다.\n{result.get('message') or '결과를 확인할 수 없습니다.'}", parent=self)

    def install_update(self):
        user = self.authority.current_user
        if not user or user.role != "admin":
            messagebox.showwarning("라이선스 관리자 업데이트", "관리자 계정만 프로그램을 업데이트할 수 있습니다.", parent=self)
            return
        package = filedialog.askopenfilename(
            parent=self,
            title="라이선스 관리자 업데이트 패키지 선택",
            filetypes=[("Cinema TMS Admin 업데이트", "Cinema-TMS-Admin-Update-*.zip"), ("ZIP 파일", "*.zip")],
        )
        if not package:
            return
        if not messagebox.askyesno(
            "라이선스 관리자 업데이트",
            "프로그램 파일을 업데이트합니다.\n"
            "관리자 계정, 발급키, 라이선스 이력 DB는 그대로 유지됩니다.\n\n계속하시겠습니까?",
            parent=self,
        ):
            return
        updater = PROJECT_ROOT / "deployment" / "apply-update.ps1"
        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if not updater.is_file() or not powershell.is_file():
            messagebox.showerror("라이선스 관리자 업데이트", "업데이트 실행 파일을 찾을 수 없습니다.", parent=self)
            return
        self.authority.logout()
        command = [
            str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater),
            "-PackagePath", package, "-ProjectRoot", str(PROJECT_ROOT),
            "-WaitForProcessId", str(os.getpid()), "-Relaunch",
        ]
        try:
            subprocess.Popen(command, cwd=PROJECT_ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as exc:
            messagebox.showerror("라이선스 관리자 업데이트", f"업데이트를 시작하지 못했습니다.\n{exc}", parent=self)
            return
        self.destroy()

    def import_existing_authority(self):
        while True:
            messagebox.showinfo(
                "라이선스 관리자 초기화",
                "이 PC에는 로그인 계정과 라이선스 발급키가 없습니다.\n\n"
                "기존 Cinema_Tms_Admin 프로젝트의 data\\licenses.db를 "
                "복사한 뒤 선택해 주세요. DB가 없으면 기존 검증키에 맞는 라이선스를 발급할 수 없습니다.",
                parent=self,
            )
            source = filedialog.askopenfilename(
                parent=self,
                title="기존 라이선스 관리자 DB 선택",
                filetypes=[("Cinema TMS 관리자 DB", "licenses.db"), ("SQLite DB", "*.db"), ("모든 파일", "*.*")],
            )
            if not source:
                return False
            try:
                self.authority.import_database(Path(source))
                messagebox.showinfo(
                    "라이선스 관리자",
                    "기존 관리자 DB를 가져왔습니다. 해당 DB에 등록된 계정으로 로그인하세요.",
                    parent=self,
                )
                return True
            except Exception as exc:
                messagebox.showerror("관리자 DB 가져오기 실패", str(exc), parent=self)

    def setup_first_admin(self):
        while True:
            fields = [
                ("username", "최초 관리자 계정", False, "admin"),
                ("password", "새 로그인 비밀번호", True, ""),
                ("confirm", "비밀번호 확인", True, ""),
            ]
            if self.authority.legacy_key_needs_password:
                fields.append(("legacy_password", "이전 키 비밀번호", True, ""))
            dialog = FormDialog(
                self, "최초 관리자 계정 생성", fields,
                note="기존 개인 발급키를 로그인 DB로 이전합니다. 사용할 로그인 비밀번호를 입력하세요.",
            )
            if not dialog.result:
                return False
            values = dialog.result
            if values["password"] != values["confirm"]:
                messagebox.showerror("라이선스 관리", "새 비밀번호 확인이 일치하지 않습니다.", parent=self)
                continue
            try:
                self.authority.bootstrap_admin(
                    values["username"], values["password"], values.get("legacy_password") or None
                )
                messagebox.showinfo(
                    "라이선스 관리",
                    "기존 발급키를 로그인 계정으로 암호화해 DB에 이전했습니다.\n이제 Windows 계정에는 귀속되지 않습니다.",
                    parent=self,
                )
                return True
            except LegacyKeyMigrationRequired as exc:
                messagebox.showerror("라이선스 관리", str(exc), parent=self)
            except Exception as exc:
                messagebox.showerror("라이선스 관리", str(exc), parent=self)

    def login(self):
        while True:
            dialog = FormDialog(
                self, "라이선스 관리자 로그인",
                [("username", "로그인 계정", False, ""), ("password", "비밀번호", True, "")],
                note="관리자 DB에 등록된 계정으로 로그인하세요. 5회 실패하면 15분 동안 잠깁니다.",
            )
            if not dialog.result:
                return False
            try:
                user = self.authority.authenticate(dialog.result["username"], dialog.result["password"])
                self.status.set(f"{user.username} · {ROLE_LABELS.get(user.role, user.role)}")
                return True
            except Exception as exc:
                messagebox.showerror("로그인 실패", str(exc), parent=self)

    def logout(self):
        self.authority.logout()
        self.request_loaded = False
        self.rebind_supersedes = ""
        self.hardware_key.set("")
        self.hardware_source.set("하드웨어 키 파일을 불러오세요.")
        self.status.set("로그인이 필요합니다.")
        self.refresh_records()
        self._refresh_permissions()
        if not self.login():
            self.destroy()
            return
        self.refresh_records()
        self._refresh_permissions()

    def close_application(self):
        self.authority.logout()
        self.destroy()

    def _refresh_permissions(self):
        user = self.authority.current_user
        role = user.role if user else ""
        can_issue = role in {"admin", "operator"} and self.authority.unlocked
        self.issue_button.configure(state="normal" if can_issue and self.request_loaded else "disabled")
        self.renew_button.configure(state="normal" if can_issue else "disabled")
        self.revoke_button.configure(state="normal" if role == "admin" else "disabled")
        self.accounts_button.configure(state="normal" if role == "admin" else "disabled")
        self.audit_button.configure(state="normal" if role == "admin" else "disabled")
        self.update_button.configure(state="normal" if role == "admin" else "disabled")

    def change_password(self):
        dialog = FormDialog(
            self, "비밀번호 변경",
            [
                ("current", "현재 비밀번호", True, ""),
                ("new", "새 비밀번호", True, ""),
                ("confirm", "새 비밀번호 확인", True, ""),
            ],
            note="변경하면 DB 안의 발급키도 새 비밀번호로 다시 암호화됩니다.",
        )
        if not dialog.result:
            return
        if dialog.result["new"] != dialog.result["confirm"]:
            messagebox.showerror("라이선스 관리", "새 비밀번호 확인이 일치하지 않습니다.", parent=self)
            return
        try:
            self.authority.change_password(dialog.result["current"], dialog.result["new"])
            messagebox.showinfo("라이선스 관리", "비밀번호를 변경했습니다.", parent=self)
        except Exception as exc:
            messagebox.showerror("라이선스 관리", str(exc), parent=self)

    def manage_accounts(self):
        window = tk.Toplevel(self)
        window.title("로그인 계정 관리")
        window.geometry("760x430")
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("id", "username", "role", "active", "failed", "last"), show="headings")
        for key, label, width in (
            ("id", "ID", 45), ("username", "계정", 130), ("role", "역할", 100),
            ("active", "상태", 70), ("failed", "실패", 55), ("last", "마지막 로그인", 220),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        def refresh():
            for item in tree.get_children():
                tree.delete(item)
            for account in self.authority.users():
                tree.insert("", "end", iid=str(account["id"]), values=(
                    account["id"], account["username"], ROLE_LABELS.get(account["role"], account["role"]),
                    "활성" if account["active"] else "비활성", account["failed_attempts"], account["last_login"] or "-",
                ))

        def add_user():
            dialog = FormDialog(
                window, "계정 추가",
                [
                    ("username", "로그인 계정", False, ""), ("password", "임시 비밀번호", True, ""),
                    ("confirm", "비밀번호 확인", True, ""), ("role", "역할", False, "operator"),
                ],
                note="역할은 admin, operator, viewer 중 하나를 입력하세요.",
            )
            if not dialog.result:
                return
            if dialog.result["password"] != dialog.result["confirm"]:
                messagebox.showerror("계정 관리", "비밀번호 확인이 일치하지 않습니다.", parent=window)
                return
            try:
                self.authority.create_user(dialog.result["username"], dialog.result["password"], dialog.result["role"].lower())
                refresh()
            except Exception as exc:
                messagebox.showerror("계정 관리", str(exc), parent=window)

        def toggle_user():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("계정 관리", "계정을 선택하세요.", parent=window)
                return
            values = tree.item(selected[0], "values")
            activate = values[3] != "활성"
            try:
                self.authority.set_user_active(int(selected[0]), activate)
                refresh()
            except Exception as exc:
                messagebox.showerror("계정 관리", str(exc), parent=window)

        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="계정 추가", command=add_user).pack(side="left")
        ttk.Button(actions, text="활성/비활성 전환", command=toggle_user).pack(side="left", padx=8)
        ttk.Button(actions, text="새로고침", command=refresh).pack(side="right")
        refresh()

    def show_audit(self):
        window = tk.Toplevel(self)
        window.title("관리자 감사 로그")
        window.geometry("920x500")
        tree = ttk.Treeview(window, columns=("time", "user", "action", "result", "detail", "pc"), show="headings")
        for key, label, width in (
            ("time", "시간(UTC+9)", 190), ("user", "계정", 100), ("action", "작업", 130),
            ("result", "결과", 55), ("detail", "상세", 260), ("pc", "PC", 120),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=12, pady=12)
        for record in self.authority.audit_records():
            tree.insert("", "end", values=(
                local_datetime(record["created_at"]), record["username"], record["action"],
                "성공" if record["success"] else "실패", record["detail"], record["workstation"],
            ))

    def load_hardware_file(self):
        source = filedialog.askopenfilename(filetypes=[("Cinema TMS 하드웨어 키", "*.tmshw"), ("모든 파일", "*.*")])
        if not source:
            return
        try:
            request = read_hardware_request(Path(source))
            self.rebind_supersedes = ""
            self.hardware_key.set(request["hardware_key"])
            if request.get("request_type") == "hardware_rebind":
                previous_key = request["previous_hardware_key"]
                previous = self.authority.latest_license_for_hardware_key(previous_key, active_only=True)
                if not previous:
                    raise ValueError("장비 변경 요청의 이전 하드웨어 키와 일치하는 활성 라이선스 이력이 없습니다.")
                self._load_previous_license(previous, hardware_rebind=True)
            else:
                previous = self.authority.latest_license_for_hardware_key(request["hardware_key"])
                if previous:
                    self._load_previous_license(previous)
                else:
                    self.hardware_source.set(f"신규 장비 · {Path(source).name}")
            self.request_loaded = True
        except Exception as exc:
            self.hardware_key.set("")
            self.hardware_source.set("하드웨어 키 파일을 다시 선택하세요.")
            self.request_loaded = False
            self.rebind_supersedes = ""
            messagebox.showerror("라이선스 관리", str(exc), parent=self)
        self._refresh_permissions()

    def _load_previous_license(self, record: dict, *, hardware_rebind: bool = False):
        self.customer.set(record["customer"])
        self.cinema.set(record["cinema"])
        self.valid_from.set(date.today().isoformat())
        previous_expiry = date.fromisoformat(record["expires_on"])
        if hardware_rebind:
            next_expiry = max(previous_expiry, date.today() + timedelta(days=1))
        else:
            next_expiry = extended_license_expiry(previous_expiry)
        self.expires_on.set(next_expiry.isoformat())
        self.auditorium_limit.set(str(max(1, int(record.get("auditorium_limit") or 1))))
        if record["status"] == "active":
            self.rebind_supersedes = record["license_id"]
        status = LICENSE_STATUS_LABELS.get(record["status"], record["status"])
        prefix = "장비 변경 요청" if hardware_rebind else "기존 사용 이력"
        operator = record.get("operator") or "-"
        self.hardware_source.set(
            f"{prefix} · {status} · {record['valid_from']}~{record['expires_on']} · 담당 {operator}"
        )

    def issue(self, supersedes: str = ""):
        user = self.authority.current_user
        if not user or user.role not in {"admin", "operator"}:
            messagebox.showwarning("라이선스 관리", "현재 로그인 계정에는 발급 권한이 없습니다.", parent=self)
            return
        if not self.request_loaded or not self.hardware_key.get():
            messagebox.showwarning("라이선스 관리", "TMS에서 저장한 .tmshw 하드웨어 키 파일을 불러오세요.", parent=self)
            return
        destination = filedialog.asksaveasfilename(
            defaultextension=".tmslic", initialfile=f"{self.cinema.get().strip() or 'cinema-tms'}.tmslic",
            filetypes=[("Cinema TMS 라이선스", "*.tmslic")],
        )
        if not destination:
            return
        try:
            envelope = self.authority.issue(
                customer=self.customer.get(), cinema=self.cinema.get(), hardware_key=self.hardware_key.get(),
                valid_from=date.fromisoformat(self.valid_from.get()), expires_on=date.fromisoformat(self.expires_on.get()),
                auditorium_limit=self.auditorium_limit.get(), destination=Path(destination),
                supersedes=supersedes or self.rebind_supersedes,
            )
            self.rebind_supersedes = ""
            self.refresh_records()
            messagebox.showinfo("라이선스 관리", f"라이선스를 발급했습니다.\n{envelope['payload']['license_id']}", parent=self)
        except Exception as exc:
            messagebox.showerror("라이선스 관리", str(exc), parent=self)

    def selected_record(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("라이선스 관리", "발급 이력을 선택하세요.", parent=self)
            return None
        return next((record for record in self.authority.records() if record["license_id"] == selected[0]), None)

    def prepare_renewal(self):
        record = self.selected_record()
        if not record:
            return
        self.customer.set(record["customer"])
        self.cinema.set(record["cinema"])
        self.hardware_key.set(record["hardware_key"])
        self.hardware_source.set("기존 발급 이력")
        self.request_loaded = True
        self.rebind_supersedes = ""
        self.valid_from.set(date.today().isoformat())
        self.expires_on.set((date.today() + timedelta(days=365)).isoformat())
        self.auditorium_limit.set(str(max(1, int(record.get("auditorium_limit") or 1))))
        self._refresh_permissions()
        self.issue(record["license_id"])

    def revoke(self):
        record = self.selected_record()
        if not record or not messagebox.askyesno(
            "라이선스 관리", "선택한 라이선스를 폐기 상태로 표시할까요?\n오프라인 PC에는 새 파일 전달 전까지 즉시 반영되지 않습니다.", parent=self
        ):
            return
        try:
            self.authority.revoke(record["license_id"])
            self.refresh_records()
        except Exception as exc:
            messagebox.showerror("라이선스 관리", str(exc), parent=self)

    def refresh_records(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for record in self.authority.records():
            action = record.get("action") or ("renewal" if record.get("supersedes") else "issue")
            limit = int(record.get("auditorium_limit") or 0)
            self.tree.insert("", "end", iid=record["license_id"], values=(
                record["license_id"], record["hardware_key"], record["customer"], record["cinema"],
                f"{limit}개" if limit else "기존/무제한", ACTION_LABELS.get(action, action),
                record.get("operator") or "-", local_datetime(record.get("issued_at", "")),
                record["expires_on"], record["status"],
            ))


if __name__ == "__main__":
    LicenseManager().mainloop()
