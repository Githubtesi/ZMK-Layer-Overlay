import ctypes
import os
import sys
import atexit
import signal
import tkinter as tk
from tkinter import simpledialog
import threading
import time
import queue
from ctypes import wintypes
from pynput import keyboard
from PIL import Image, ImageTk, ImageDraw
import pygetwindow as gw
from screeninfo import get_monitors
import pystray
from pystray import MenuItem as item

# DWORD_PTR は ctypes.wintypes に無い環境があるため自前定義
DWORD_PTR = ctypes.c_size_t
PDWORD_PTR = ctypes.POINTER(DWORD_PTR)

# --- v7: カーソル画像を少し小さく調整（v6の約90%） ---
# --- 設定項目 ---
DURATION_MS = 800          # オーバーレイ表示時間（ms）

# キュー（スレッド間安全通信用）
ui_queue = queue.Queue()

SMTO_ABORTIFHUNG = 0x0002
TIMEOUT_MS = 50

IMC_GETOPENSTATUS = 0x0005

# --- Windows window style ---
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

# --- マウスカーソル画像変更用 ---
# v6: 通常の矢印カーソルは変更せず、文字入力欄で出る I ビームカーソルだけを
# 小さめのモード別 .cur / .ani ファイルに置き換える。
IMAGE_CURSOR = 2
LR_LOADFROMFILE = 0x00000010
OCR_NORMAL = 32512          # 通常の矢印カーソル（今回は変更しない）
OCR_IBEAM = 32513           # 文字入力欄で表示される I ビームカーソル
SPI_SETCURSORS = 0x0057     # システムカーソルを既定状態へ戻す
SPIF_SENDCHANGE = 0x0002     # 変更をシステムへ通知

user32 = ctypes.windll.user32
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE if hasattr(wintypes, "HINSTANCE") else wintypes.HANDLE,
    wintypes.LPCWSTR,
    wintypes.UINT,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.LoadImageW.restype = wintypes.HANDLE

user32.SetSystemCursor.argtypes = [wintypes.HANDLE, wintypes.DWORD]
user32.SetSystemCursor.restype = wintypes.BOOL

user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    wintypes.UINT,
]
user32.SystemParametersInfoW.restype = wintypes.BOOL


def restore_windows_cursors():
    """Windowsのシステムカーソルを現在の設定に再読み込みして復旧する。"""
    try:
        user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)
    except Exception as e:
        print(f"Restore Windows Cursor Error: {e}")


def _restore_and_exit(signum=None, frame=None):
    restore_windows_cursors()
    raise SystemExit(0)


# 正常終了、Ctrl+C、終了シグナル時はできる限り標準カーソルへ戻す。
atexit.register(restore_windows_cursors)
for _sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
    if _sig is not None:
        try:
            signal.signal(_sig, _restore_and_exit)
        except Exception:
            pass

# 64bit / 32bit 両対応
if hasattr(ctypes.windll.user32, "GetWindowLongPtrW"):
    GetWindowLongPtr = ctypes.windll.user32.GetWindowLongPtrW
    SetWindowLongPtr = ctypes.windll.user32.SetWindowLongPtrW
else:
    GetWindowLongPtr = ctypes.windll.user32.GetWindowLongW
    SetWindowLongPtr = ctypes.windll.user32.SetWindowLongW

GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
GetWindowLongPtr.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, GetWindowLongPtr.restype]
SetWindowLongPtr.restype = GetWindowLongPtr.restype

ctypes.windll.user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    PDWORD_PTR
]
ctypes.windll.user32.SendMessageTimeoutW.restype = wintypes.LPARAM

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]

ctypes.windll.user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD)
]
ctypes.windll.user32.GetWindowThreadProcessId.restype = wintypes.DWORD

ctypes.windll.user32.GetGUIThreadInfo.argtypes = [
    wintypes.DWORD,
    ctypes.POINTER(GUITHREADINFO)
]
ctypes.windll.user32.GetGUIThreadInfo.restype = wintypes.BOOL


def make_click_through_noactivate(toplevel):
    """
    v2: 黒い四角表示対策のため、Windows拡張スタイル変更は行わない。
    WS_EX_LAYERED / WS_EX_TRANSPARENT は環境によって Tk の描画と衝突することがある。
    """
    return


def get_focus_hwnd():
    """
    前面ウィンドウではなく、実際にフォーカスを持っている子ウィンドウを取得する。
    Outlook / WebView / Office系アプリ対策。
    """
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd:
        return None

    pid = wintypes.DWORD()
    thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    gui_info = GUITHREADINFO()
    gui_info.cbSize = ctypes.sizeof(GUITHREADINFO)

    if ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)):
        if gui_info.hwndFocus:
            return gui_info.hwndFocus
        if gui_info.hwndCaret:
            return gui_info.hwndCaret
        if gui_info.hwndActive:
            return gui_info.hwndActive

    return hwnd


def send_ime_message_timeout(ime_hwnd, wparam, lparam=0):
    result = DWORD_PTR(0)

    ok = ctypes.windll.user32.SendMessageTimeoutW(
        ime_hwnd,
        WM_IME_CONTROL,
        wparam,
        lparam,
        SMTO_ABORTIFHUNG,
        TIMEOUT_MS,
        ctypes.byref(result)
    )

    if ok == 0:
        return None

    return result.value


def process_queue():
    """Tkinter mainloopから定期的にUI更新を処理"""
    try:
        while True:
            func = ui_queue.get_nowait()
            try:
                func()
            except Exception as e:
                print(f"UI Queue Error: {e}")
    except queue.Empty:
        pass

    if overlay_app is not None and overlay_app.is_running:
        overlay_app.root.after(50, process_queue)


def set_ime_status(mode):
    try:
        hwnd = get_focus_hwnd()
        if not hwnd:
            return
        ime_hwnd = ctypes.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_hwnd:
            return
        ctypes.windll.user32.SendMessageA(ime_hwnd, 0x0283, 0x0006, mode)
    except Exception as e:
        print(f"IME Control Error: {e}")


if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_FOLDER = os.path.join(BASE_DIR, "layers")
CURSOR_FOLDER = os.path.join(BASE_DIR, "cursors")
TRANS_COLOR = "#abcdef"

# False にすると従来の追従ラベルを非表示にする。
# ちらつきが気になる場合は False 推奨。
SHOW_STATUS_OVERLAY = True

# True にすると F13/F15 の状態を I ビームカーソル画像で表す。
USE_CURSOR_MODE = True

MODE_NAMES = {
    "f13": "I 英語",
    "f14": "Mouse",
    "f15": "I 数字",
    "f16": "App",
    "f19": "Edit",
}

MODE_NAMES_JP = {
    "f13": "I 日本語",
    "f14": "Mouse",
    "f15": "I 数字",
    "f16": "App",
    "f19": "Edit",
}

# I ビームカーソル画像を変更する対象。
# Mouseモード(f14)は必ずWindows既定カーソルへ戻す。
CUSTOM_CURSOR_MODE_KEYS = {"f13", "f15"}

# --- IME 状態取得用 ---
WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001

IME_CMODE_NATIVE = 0x0001
IME_CMODE_KATAKANA = 0x0002
IME_CMODE_FULLSHAPE = 0x0008
IME_CMODE_ROMAN = 0x0010

# --- IMM direct context API ---
ctypes.windll.imm32.ImmGetContext.argtypes = [wintypes.HWND]
ctypes.windll.imm32.ImmGetContext.restype = wintypes.HANDLE

ctypes.windll.imm32.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
ctypes.windll.imm32.ImmReleaseContext.restype = wintypes.BOOL

ctypes.windll.imm32.ImmGetOpenStatus.argtypes = [wintypes.HANDLE]
ctypes.windll.imm32.ImmGetOpenStatus.restype = wintypes.BOOL

ctypes.windll.imm32.ImmGetConversionStatus.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD)
]
ctypes.windll.imm32.ImmGetConversionStatus.restype = wintypes.BOOL


def get_ime_input_status():
    """
    戻り値:
        "japanese"      -> 日本語入力
        "half_romaji"   -> 半角英数
        "full_romaji"   -> 全角英数
        "off"           -> IME OFF
        "unknown"       -> 取得失敗
    """
    try:
        hwnd = get_focus_hwnd()
        if not hwnd:
            return "unknown"

        # 1) まず直接IMEコンテキストから取得する
        himc = ctypes.windll.imm32.ImmGetContext(hwnd)
        if himc:
            try:
                open_status = ctypes.windll.imm32.ImmGetOpenStatus(himc)

                if not open_status:
                    return "off"

                conv_mode = wintypes.DWORD(0)
                sentence_mode = wintypes.DWORD(0)

                ok = ctypes.windll.imm32.ImmGetConversionStatus(
                    himc,
                    ctypes.byref(conv_mode),
                    ctypes.byref(sentence_mode)
                )

                if ok:
                    mode = conv_mode.value

                    is_native = bool(mode & IME_CMODE_NATIVE)
                    is_fullshape = bool(mode & IME_CMODE_FULLSHAPE)

                    if is_native:
                        return "japanese"

                    if is_fullshape:
                        return "full_romaji"

                    return "half_romaji"

            finally:
                ctypes.windll.imm32.ImmReleaseContext(hwnd, himc)

        # 2) 直接取得できない場合は、従来の既定IMEウィンドウ方式にフォールバック
        ime_hwnd = ctypes.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_hwnd:
            return "unknown"

        open_status = send_ime_message_timeout(
            ime_hwnd,
            IMC_GETOPENSTATUS,
            0
        )

        if open_status is None:
            return "unknown"

        if not open_status:
            return "off"

        conv_mode = send_ime_message_timeout(
            ime_hwnd,
            IMC_GETCONVERSIONMODE,
            0
        )

        if conv_mode is None:
            return "unknown"

        is_native = bool(conv_mode & IME_CMODE_NATIVE)
        is_fullshape = bool(conv_mode & IME_CMODE_FULLSHAPE)

        if is_native:
            return "japanese"

        if is_fullshape:
            return "full_romaji"

        return "half_romaji"

    except Exception as e:
        print(f"IME Status Error: {e}")
        return "unknown"


class LayerOverlay:
    def __init__(self):
        # 前回異常終了してカーソルが残っていた場合も、起動時に一度復旧する。
        restore_windows_cursors()

        self.root = tk.Tk()
        self.root.withdraw()

        self.is_running = True
        self.listener = None

        self._last_mouse_pos = None
        self.mouse_move_threshold = 12

        # 写真レイヤー用オーバーレイ
        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-transparentcolor", TRANS_COLOR)
        self.overlay.config(bg=TRANS_COLOR)

        self.label = tk.Label(self.overlay, bg=TRANS_COLOR)
        self.label.pack()
        self.overlay.withdraw()

        # 状態管理
        self.current_key = None
        self.press_start_time = 0
        self.after_id = None
        self.duration_ms = DURATION_MS

        # 写真レイヤー表示だけを制御する
        self.is_enabled = False

        # ステータス表示の位置モード
        # False = 右下固定
        # True  = マウス追従
        self.is_mouse_follow_enabled = False

        # 初期設定: 写真表示OFF、カーソル変更ON、状態ラベルON、追従ON
        self.show_status_overlay = SHOW_STATUS_OVERLAY
        self.use_cursor_mode = USE_CURSOR_MODE
        self._cursor_mode_key = None

        # 追従間隔。30msはTkのgeometry連打になりやすいので少し緩める
        self.mouse_follow_interval_ms = 120
        self.ime_watch_interval_ms = 250

        self.active_mode_key = "f13"
        self.last_ime_status = None
        self.last_valid_ime_status = "half_romaji"

        # 追従時の無駄なgeometry更新を避けるためのキャッシュ
        self._status_size = None
        self._last_status_geometry = None
        self._last_monitor_fetch = 0
        self._monitor_cache = None

        # ステータス表示用オーバーレイ
        self.status_overlay = tk.Toplevel(self.root)
        self.status_overlay.overrideredirect(True)
        self.status_overlay.attributes("-topmost", True)
        # self.status_overlay.attributes("-alpha", 0.92)
        self.status_overlay.config(bg="#F6D7E0")

        # 外枠フレーム
        self.status_frame = tk.Frame(
            self.status_overlay,
            bg="#F6D7E0",
            bd=0,
            padx=2,
            pady=2
        )
        self.status_frame.pack()

        # 中身ラベル
        self.status_label = tk.Label(
            self.status_frame,
            text="BASE",
            font=("Yu Gothic UI", 11, "bold"),
            bg="#FFF8FB",
            fg="#333333",
            padx=14,
            pady=6,
            relief="flat"
        )
        self.status_label.pack()

        self.recalc_status_size()
        if not self.show_status_overlay:
            self.status_overlay.withdraw()
        # 黒い四角表示対策: Tkinter標準の描画に任せる
        # make_click_through_noactivate(self.status_overlay)

        # トレイメニュー
        self.setup_tray()
        self.ui_queue = ui_queue

        # 定期処理は最後に1回だけ登録
        self.root.after(50, process_queue)
        self.root.after(200, self.watch_ime_status)
        if self.show_status_overlay and self.is_mouse_follow_enabled:
            self.root.after(self.mouse_follow_interval_ms, self.follow_mouse)

        # 初期位置と初期表示
        if self.show_status_overlay:
            self.update_mode_status(self.active_mode_key, self.last_valid_ime_status)
            self.place_status_overlay(force=True)

    def setup_tray(self):
        icon_img = self.create_menu_icon()
        menu = (
            item('写真表示 有効/無効', self.toggle_enabled, checked=lambda item: self.is_enabled),
            item('カーソル変更 有効/無効', self.toggle_cursor_mode, checked=lambda item: self.use_cursor_mode),
            item('状態ラベル表示 有効/無効', self.toggle_status_overlay, checked=lambda item: self.show_status_overlay),
            item('追従', self.toggle_mouse_follow, checked=lambda item: self.is_mouse_follow_enabled),
            item('表示秒数の設定', self.set_duration),
            item('終了', self.quit_app)
        )
        self.icon = pystray.Icon("LayerOverlay", icon_img, "Layer Overlay Tool", menu)

    def create_menu_icon(self):
        img = Image.new('RGB', (64, 64), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.ellipse((10, 10, 54, 54), fill=(0, 120, 215))
        return img

    def get_cursor_path_candidates(self, key_name, ime_status=None):
        """
        I ビームカーソルファイルの探索順。
        Mouseモード(f14)はここでは候補を返さず、標準カーソルに戻す。

        F13 + 英数/IME OFF : I 英語
        F13 + 日本語入力   : I 日本語（赤）
        F15 + 英数/IME OFF : I 数字（黒）
        F15 + 日本語入力   : I 数字（赤）
        """
        key_lower = (key_name or "").lower()

        if key_lower not in CUSTOM_CURSOR_MODE_KEYS:
            return []

        is_japanese = ime_status == "japanese"

        if key_lower == "f13":
            stems = ["ibeam_key_japanese", "f13_ibeam_japanese", "key_japanese"] if is_japanese else ["ibeam_key", "f13_ibeam", "key"]
        elif key_lower == "f15":
            stems = ["ibeam_num_japanese", "f15_ibeam_japanese", "num_japanese"] if is_japanese else ["ibeam_num", "f15_ibeam", "num"]
        else:
            stems = [key_lower]

        candidates = []
        for stem in stems:
            candidates.extend([
                os.path.join(CURSOR_FOLDER, f"{stem}.cur"),
                os.path.join(CURSOR_FOLDER, f"{stem}.ani"),
            ])

        return candidates

    def set_cursor_for_mode(self, key_name, ime_status=None):
        """F13/F15の状態に応じて I ビームカーソルだけを置き換える。Mouse等は標準へ戻す。"""
        key_lower = (key_name or "").lower()

        # Mouseモード(f14)、未指定モード、カーソル変更OFFでは必ず標準カーソルに戻す。
        # 通常の矢印カーソルは変更しない。
        if (not self.use_cursor_mode) or key_lower not in CUSTOM_CURSOR_MODE_KEYS:
            self.restore_system_cursor()
            return

        cursor_path = None
        for path in self.get_cursor_path_candidates(key_name, ime_status):
            if os.path.exists(path):
                cursor_path = path
                break

        if not cursor_path:
            # カーソルファイルが無い場合は前のカーソルを残さず、標準へ戻す。
            self.restore_system_cursor()
            return

        if cursor_path == self._cursor_mode_key:
            return

        hcur = user32.LoadImageW(
            None,
            cursor_path,
            IMAGE_CURSOR,
            0,
            0,
            LR_LOADFROMFILE,
        )
        if not hcur:
            print(f"Cursor Load Error: {cursor_path}")
            self.restore_system_cursor()
            return

        ok = user32.SetSystemCursor(hcur, OCR_IBEAM)
        if not ok:
            print(f"SetSystemCursor Error: {cursor_path}")
            self.restore_system_cursor()
            return

        self._cursor_mode_key = cursor_path

    def restore_system_cursor(self):
        """アプリ終了時・Mouseモード時・カーソル変更OFF時にWindows標準カーソルへ戻す。"""
        restore_windows_cursors()
        self._cursor_mode_key = None

    def toggle_enabled(self, icon, item):
        def do_toggle():
            self.is_enabled = not self.is_enabled
            if not self.is_enabled:
                self.hide_layer("forced")
        ui_queue.put(do_toggle)

    def toggle_mouse_follow(self, icon, item):
        def do_toggle():
            self.is_mouse_follow_enabled = not self.is_mouse_follow_enabled
            if self.show_status_overlay:
                self.place_status_overlay(force=True)
                if self.is_mouse_follow_enabled:
                    self.root.after(self.mouse_follow_interval_ms, self.follow_mouse)
        ui_queue.put(do_toggle)

    def toggle_cursor_mode(self, icon, item):
        def do_toggle():
            self.use_cursor_mode = not self.use_cursor_mode
            if self.use_cursor_mode:
                self.set_cursor_for_mode(self.active_mode_key, self.last_valid_ime_status)
            else:
                self.restore_system_cursor()
        ui_queue.put(do_toggle)

    def toggle_status_overlay(self, icon, item):
        def do_toggle():
            self.show_status_overlay = not self.show_status_overlay
            if self.show_status_overlay:
                self.status_overlay.deiconify()
                self.update_mode_status(self.active_mode_key, self.last_ime_status)
                self.place_status_overlay(force=True)
                if self.is_mouse_follow_enabled:
                    self.root.after(self.mouse_follow_interval_ms, self.follow_mouse)
            else:
                self.status_overlay.withdraw()
        ui_queue.put(do_toggle)

    def set_duration(self, icon, item):
        def ask():
            new_sec = simpledialog.askfloat(
                "設定",
                "表示秒数を入力:",
                initialvalue=self.duration_ms / 1000,
                minvalue=0.1,
                maxvalue=60.0
            )
            if new_sec is not None:
                self.duration_ms = int(new_sec * 1000)
        ui_queue.put(ask)

    def quit_app(self, icon=None, item=None):
        def do_quit():
            self.is_running = False
            try:
                if self.listener:
                    self.listener.stop()
            except Exception as e:
                print(f"Listener Stop Error: {e}")
            try:
                self.icon.stop()
            except Exception as e:
                print(f"Tray Stop Error: {e}")
            try:
                self.restore_system_cursor()
            except Exception as e:
                print(f"Cursor Restore Error: {e}")
            try:
                self.root.quit()
                self.root.destroy()
            except Exception as e:
                print(f"Tk Quit Error: {e}")
        ui_queue.put(do_quit)

    def get_monitors_cached(self):
        now = time.time()
        if self._monitor_cache is None or now - self._last_monitor_fetch > 1.0:
            self._monitor_cache = get_monitors()
            self._last_monitor_fetch = now
        return self._monitor_cache

    def get_active_monitor(self):
        try:
            window = gw.getActiveWindow()
            if window:
                mid_x = window.left + window.width / 2
                mid_y = window.top + window.height / 2
                for m in self.get_monitors_cached():
                    if m.x <= mid_x <= m.x + m.width and m.y <= mid_y <= m.y + m.height:
                        return m
        except Exception:
            pass
        monitors = self.get_monitors_cached()
        return monitors[0]

    def get_monitor_from_point(self, x, y):
        for m in self.get_monitors_cached():
            if m.x <= x <= m.x + m.width and m.y <= y <= m.y + m.height:
                return m
        return self.get_monitors_cached()[0]

    def show_layer(self, key_name):
        if not self.is_enabled:
            return
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None

        img_path = os.path.join(IMAGE_FOLDER, f"{key_name.lower()}.png")
        if not os.path.exists(img_path):
            return

        monitor = self.get_active_monitor()
        try:
            with Image.open(img_path) as img:
                img = img.convert("RGBA")
                max_w, max_h = int(monitor.width * 0.8), int(monitor.height * 0.8)
                img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(img)
                self.label.config(image=self.photo)
                x = monitor.x + (monitor.width - img.width) // 2
                y = monitor.y + (monitor.height - img.height) // 2
                self.overlay.geometry(f"{img.width}x{img.height}+{x}+{y}")
                self.overlay.deiconify()
                self.start_hide_timer()
        except Exception as e:
            print(f"Show Layer Error: {e}")

    def start_hide_timer(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)
        current_id = self.root.after(self.duration_ms, lambda: self.hide_layer(current_id))
        self.after_id = current_id

    def hide_layer(self, called_id):
        if called_id == "forced" or called_id == self.after_id:
            self.overlay.withdraw()
            self.after_id = None

    def recalc_status_size(self):
        """文字変更時だけサイズを再計算。追従中に毎回update_idletasksしない。"""
        try:
            self.status_label.update_idletasks()
            w = self.status_label.winfo_reqwidth() + 8
            h = self.status_label.winfo_reqheight() + 4
            self._status_size = (w, h)
        except Exception as e:
            print(f"Status Size Error: {e}")
            self._status_size = (120, 36)

    def place_status_overlay(self, force=False):
        if not self.show_status_overlay:
            return

        if self._status_size is None:
            self.recalc_status_size()

        w, h = self._status_size

        if self.is_mouse_follow_enabled:
            mouse_x = self.root.winfo_pointerx()
            mouse_y = self.root.winfo_pointery()

            if not force and self._last_mouse_pos is not None:
                last_x, last_y = self._last_mouse_pos
                if (
                        abs(mouse_x - last_x) < self.mouse_move_threshold
                        and abs(mouse_y - last_y) < self.mouse_move_threshold
                ):
                    return

            self._last_mouse_pos = (mouse_x, mouse_y)

            offset_x = 18
            offset_y = 24

            x = mouse_x + offset_x
            y = mouse_y + offset_y

            target_monitor = self.get_monitor_from_point(mouse_x, mouse_y)

            # 右にはみ出す場合は左側へ
            if x + w > target_monitor.x + target_monitor.width:
                x = mouse_x - w - offset_x

            # 下にはみ出す場合は上側へ
            if y + h > target_monitor.y + target_monitor.height:
                y = mouse_y - h - offset_y

            # 画面外に出ないよう補正
            if x < target_monitor.x:
                x = target_monitor.x
            if y < target_monitor.y:
                y = target_monitor.y

        else:
            # 右下固定表示
            monitor = self.get_active_monitor()
            x = monitor.x + monitor.width - w - 20
            y = monitor.y + monitor.height - h - 60

        geometry = f"{w}x{h}+{int(x)}+{int(y)}"

        if force or geometry != self._last_status_geometry:
            self.status_overlay.geometry(geometry)
            self._last_status_geometry = geometry

    def follow_mouse(self):
        """
        追従ONのときだけ、ステータス表示をマウスに追従させる。
        写真表示の有効/無効とは独立。
        """
        try:
            if self.is_running and self.show_status_overlay and self.is_mouse_follow_enabled:
                self.place_status_overlay()
        except Exception as e:
            print(f"Mouse Follow Error: {e}")

        if self.is_running and self.show_status_overlay and self.is_mouse_follow_enabled:
            self.root.after(self.mouse_follow_interval_ms, self.follow_mouse)

    def handle_mode_key(self, key_name):
        """
        F13〜F24が押されたときの表示更新。
        pynput側ではIME取得せず、Tkinter側で安全に処理する。
        """
        self.press_start_time = time.time()

        ime_status = self.last_valid_ime_status

        if ime_status not in ("japanese", "half_romaji", "full_romaji", "off"):
            ime_status = "half_romaji"

        self.active_mode_key = key_name.lower()
        self.last_ime_status = ime_status

        # ちらつき対策: 追従ラベルではなく I ビームカーソル画像を変更する
        self.set_cursor_for_mode(key_name, ime_status)

        # 従来の写真レイヤー表示はトレイの「写真表示」で有効/無効を切替可能
        self.show_layer(key_name)
        self.update_mode_status(key_name, ime_status)

    def update_mode_status(self, key_name, ime_status=None):
        # IME状態も含めた I ビームカーソルファイルがある場合は、IME切替時にもカーソルを更新する
        self.set_cursor_for_mode(key_name, ime_status)

        if not self.show_status_overlay:
            return

        key_lower = key_name.lower()

        if key_lower not in MODE_NAMES:
            mode = "None"
            fg_color = "#333333"
            bg_color = "#FFF8FB"
            border_color = "#F6D7E0"

        elif ime_status == "japanese":
            mode = MODE_NAMES_JP.get(key_lower, MODE_NAMES.get(key_lower, "None"))
            fg_color = "#D9385E"
            bg_color = "#FFF0F5"
            border_color = "#F5B7C8"

        elif ime_status in ("half_romaji", "full_romaji", "off"):
            mode = MODE_NAMES.get(key_lower, "None")
            fg_color = "#333333"
            bg_color = "#F9FCFF"
            border_color = "#C9DCEC"

        else:
            mode = MODE_NAMES.get(key_lower, "None") + "?"
            fg_color = "#333333"
            bg_color = "#FFF8FB"
            border_color = "#D9D9D9"

        self.status_label.config(
            text=mode,
            fg=fg_color,
            bg=bg_color
        )

        self.status_frame.config(bg=border_color)
        self.status_overlay.config(bg=border_color)

        # 文字が変わったときだけサイズ再計算
        self.recalc_status_size()
        self.place_status_overlay(force=True)

        # Everything等で表示が古いまま残る対策
        self.status_overlay.lift()
        self.status_overlay.update_idletasks()

    def watch_ime_status(self):
        """
        IME状態を監視する。
        Everythingなどでunknownになっても表示処理を止めない。
        """
        try:
            ime_status = get_ime_input_status()

            # 確認用。安定したらコメントアウトしてOK
            # print("IME:", ime_status, "LAST:", self.last_valid_ime_status)

            if ime_status == "unknown":
                ime_status = self.last_valid_ime_status
            else:
                self.last_valid_ime_status = ime_status

            if ime_status != self.last_ime_status:
                self.last_ime_status = ime_status
                self.update_mode_status(self.active_mode_key, ime_status)

        except Exception as e:
            print(f"IME Watch Error: {e}")

        if self.is_running:
            self.root.after(self.ime_watch_interval_ms, self.watch_ime_status)


    def run(self):
        # pystrayはTkinterなど他のイベントループと併用する場合、run_detachedが安全
        try:
            self.icon.run_detached()
        except NotImplementedError:
            # Windows以外などで未対応の場合だけフォールバック
            threading.Thread(target=self.icon.run, daemon=True).start()

        try:
            self.place_status_overlay(force=True)
            self.root.mainloop()
        finally:
            self.restore_system_cursor()


# グローバルインスタンス
overlay_app = None


def on_press(key):
    try:
        if overlay_app is None or not overlay_app.is_running:
            return

        if hasattr(key, 'name'):
            k = key.name
        elif hasattr(key, 'char') and key.char:
            k = key.char
        else:
            k = str(key).strip("'")



        # F13〜F24 判定
        is_target_f_key = k and k.lower().startswith('f') and \
                         k.lower()[1:].isdigit() and 13 <= int(k.lower()[1:]) <= 24

        # その他のキーが押されたらオーバーレイを消す
        if not is_target_f_key:
            if overlay_app.after_id is not None:
                ui_queue.put(lambda: overlay_app.hide_layer("forced"))
            return

        # Fキー（F13〜F24）の処理
        # Fキー（F13〜F24）の処理
        if overlay_app.current_key != k:
            overlay_app.current_key = k
            ui_queue.put(lambda k=k: overlay_app.handle_mode_key(k))

    except Exception as e:
        print(f"Error in on_press: {e}")


def on_release(key):
    try:
        if overlay_app is None or not overlay_app.is_running:
            return

        if hasattr(key, 'name'):
            k = key.name
        elif hasattr(key, 'char') and key.char:
            k = key.char
        else:
            k = str(key).strip("'")

        if k == overlay_app.current_key:
            overlay_app.current_key = None
            # リリース時にタイマーを開始（すでにshow_layerで開始しているが念のため）
            ui_queue.put(lambda: overlay_app.start_hide_timer())

    except Exception as e:
        print(f"Error in on_release: {e}")


if __name__ == '__main__':
    try:
        overlay_app = LayerOverlay()
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        overlay_app.listener = listener
        listener.start()
        overlay_app.run()
    finally:
        restore_windows_cursors()
