"""Windows-native text entry with proper inline IME composition support."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    GWLP_WNDPROC = -4
    WS_CHILD = 0x40000000
    WS_VISIBLE = 0x10000000
    WS_TABSTOP = 0x00010000
    ES_AUTOHSCROLL = 0x0080
    ES_PASSWORD = 0x0020
    WS_EX_CLIENTEDGE = 0x00000200
    WM_KEYDOWN = 0x0100
    WM_CHAR = 0x0102
    WM_KILLFOCUS = 0x0008
    WM_IME_ENDCOMPOSITION = 0x010E
    WM_IME_COMPOSITION = 0x010F
    WM_CUT = 0x0300
    WM_COPY = 0x0301
    WM_PASTE = 0x0302
    WM_CLEAR = 0x0303
    WM_UNDO = 0x0304
    WM_SETFONT = 0x0030
    EM_SETPASSWORDCHAR = 0x00CC
    VK_TAB = 0x09
    VK_RETURN = 0x0D
    VK_ESCAPE = 0x1B
    VK_SHIFT = 0x10
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    user32.CreateWindowExW.argtypes = (
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    )
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = (wintypes.HWND,)
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.MoveWindow.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL)
    user32.MoveWindow.restype = wintypes.BOOL
    user32.SetFocus.argtypes = (wintypes.HWND,)
    user32.SetFocus.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.SetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
    user32.SetWindowTextW.restype = wintypes.BOOL
    user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.SendMessageW.restype = LRESULT
    user32.GetKeyState.argtypes = (ctypes.c_int,)
    user32.GetKeyState.restype = ctypes.c_short
    user32.CallWindowProcW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallWindowProcW.restype = LRESULT
    user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    gdi32.DeleteObject.restype = wintypes.BOOL


class WindowsImeEntry(tk.Frame):
    """Entry-compatible widget backed by the native Windows EDIT control.

    Tk's Windows text widgets can place the active Korean composition in a
    detached helper window. A child Win32 EDIT control uses TSF/IME inline and
    keeps the composing syllable, caret, and candidate UI inside the field.
    Other platforms retain a normal Tk entry as a compatibility fallback.
    """

    def __init__(self, master=None, *, textvariable=None, width=20, show="", **kwargs):
        self.variable = textvariable or tk.StringVar(master=master)
        self.character_width = max(1, int(width))
        self.show = show
        font_name = kwargs.pop("font", "TkTextFont")
        font = tkfont.nametofont(font_name, root=master)
        requested_width = max(40, font.measure("0") * self.character_width + 14)
        requested_height = max(24, font.metrics("linespace") + 10)
        super().__init__(
            master,
            width=requested_width,
            height=requested_height,
            takefocus=True,
            background="#ffffff",
            highlightthickness=1,
            highlightcolor="#0078d4",
            highlightbackground="#a7a7a7",
            borderwidth=0,
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._editor = 0
        self._font_handle = 0
        self._original_proc = 0
        self._window_proc = None
        self._syncing = False
        self._fallback = None
        self._trace_id = self.variable.trace_add("write", self._sync_to_editor)
        self.bind("<Map>", self._create_editor, add="+")
        self.bind("<Configure>", self._resize_editor, add="+")
        self.bind("<Destroy>", self._destroy_editor, add="+")
        self.bind("<Button-1>", lambda _event: self.focus_set(), add="+")
        self.after_idle(self._create_editor)

    def _create_editor(self, _event=None):
        if self._editor or not self.winfo_exists():
            return
        if os.name != "nt":
            self._fallback = tk.Entry(self, textvariable=self.variable, show=self.show, relief="flat", borderwidth=0)
            self._fallback.pack(fill="both", expand=True, padx=3, pady=2)
            return
        self.update_idletasks()
        style = WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL
        if self.show:
            style |= ES_PASSWORD
        editor = user32.CreateWindowExW(
            WS_EX_CLIENTEDGE,
            "EDIT",
            self.variable.get(),
            style,
            0,
            0,
            max(1, self.winfo_width()),
            max(1, self.winfo_height()),
            self.winfo_id(),
            None,
            None,
            None,
        )
        if not editor:
            raise ctypes.WinError(ctypes.get_last_error())
        self._editor = int(editor)
        self._font_handle = int(
            gdi32.CreateFontW(-15, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Malgun Gothic") or 0
        )
        if self._font_handle:
            user32.SendMessageW(editor, WM_SETFONT, self._font_handle, 1)
        if self.show:
            user32.SendMessageW(editor, EM_SETPASSWORDCHAR, ord("●"), 0)
        self._window_proc = WNDPROC(self._dispatch_native_message)
        original = user32.SetWindowLongPtrW(editor, GWLP_WNDPROC, ctypes.cast(self._window_proc, ctypes.c_void_p))
        if not original:
            error = ctypes.get_last_error()
            if error:
                raise ctypes.WinError(error)
        self._original_proc = int(original)
        self._resize_editor()

    def _dispatch_native_message(self, hwnd, message, wparam, lparam):
        if message == WM_KEYDOWN:
            if wparam == VK_TAB:
                self._sync_from_editor()
                reverse = bool(user32.GetKeyState(VK_SHIFT) & 0x8000)
                self.after_idle(lambda: self._focus_relative(reverse))
                return 0
            if wparam in (VK_RETURN, VK_ESCAPE):
                self._sync_from_editor()
                sequence = "<Return>" if wparam == VK_RETURN else "<Escape>"
                self.after_idle(lambda: self.winfo_toplevel().event_generate(sequence))
                return 0
        result = user32.CallWindowProcW(self._original_proc, hwnd, message, wparam, lparam)
        if message in (
            WM_CHAR,
            WM_KILLFOCUS,
            WM_IME_ENDCOMPOSITION,
            WM_IME_COMPOSITION,
            WM_CUT,
            WM_PASTE,
            WM_CLEAR,
            WM_UNDO,
        ):
            self._sync_from_editor()
        return result

    def _focus_relative(self, reverse=False):
        target = self.tk_focusPrev() if reverse else self.tk_focusNext()
        if target is not None and target is not self:
            target.focus_set()

    def _native_text(self):
        if not self._editor:
            return self.variable.get()
        length = user32.GetWindowTextLengthW(self._editor)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(self._editor, buffer, len(buffer))
        return buffer.value

    def _sync_from_editor(self):
        if not self._editor or self._syncing:
            return
        value = self._native_text()
        if value == self.variable.get():
            return
        self._syncing = True
        try:
            self.variable.set(value)
        finally:
            self._syncing = False

    def _sync_to_editor(self, *_args):
        if not self._editor or self._syncing:
            return
        value = self.variable.get()
        if value == self._native_text():
            return
        self._syncing = True
        try:
            user32.SetWindowTextW(self._editor, value)
        finally:
            self._syncing = False

    def _resize_editor(self, _event=None):
        if self._editor:
            user32.MoveWindow(self._editor, 0, 0, max(1, self.winfo_width()), max(1, self.winfo_height()), True)

    def _destroy_editor(self, event=None):
        if event is not None and event.widget is not self:
            return
        try:
            self.variable.trace_remove("write", self._trace_id)
        except (tk.TclError, AttributeError):
            pass
        if os.name == "nt" and self._editor:
            user32.DestroyWindow(self._editor)
            self._editor = 0
        if os.name == "nt" and self._font_handle:
            gdi32.DeleteObject(self._font_handle)
            self._font_handle = 0
        self._window_proc = None

    def focus_set(self):
        if self._fallback is not None:
            self._fallback.focus_set()
        elif os.name == "nt" and self._editor:
            user32.SetFocus(self._editor)
        else:
            super().focus_set()

    focus = focus_set

    def get(self):
        self._sync_from_editor()
        return self.variable.get()
