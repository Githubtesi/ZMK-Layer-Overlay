import ctypes
import os
import sys
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

# --- 設定項目 ---
DURATION_MS = 800          # オーバーレイ表示時間（ms）

# キュー（スレッド間安全通信用）
ui_queue = queue.Queue()

SMTO_ABORTIFHUNG = 0x0002
TIMEOUT_MS = 50


IMC_GETOPENSTATUS = 0x0005

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
            func()
    except queue.Empty:
        pass
    overlay_app.root.after(50, process_queue)


def set_ime_status(mode):
    try:
        hwnd = get_focus_hwnd()
        ime_hwnd = ctypes.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        ctypes.windll.user32.SendMessageA(ime_hwnd, 0x0283, 0x0006, mode)
    except Exception as e:
        print(f"IME Control Error: {e}")


if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_FOLDER = os.path.join(BASE_DIR, "layers")
TRANS_COLOR = "#abcdef"


MODE_NAMES = {
    "f13": "Keyboard",
    "f14": "Mouse",
    "f15": "Num",
    "f16": "App",
    "f19": "Edit",
}

MODE_NAMES_JP = {
    "f13": "キーボード",
    "f14": "マウス",
    "f15": "テンキー",
    "f16": "アプリ選択",
    "f19": "編集",
}



# --- IME 状態取得用 ---
WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001

IME_CMODE_NATIVE = 0x0001
IME_CMODE_KATAKANA = 0x0002
IME_CMODE_FULLSHAPE = 0x0008
IME_CMODE_ROMAN = 0x0010

ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND
ctypes.windll.imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
ctypes.windll.imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
ctypes.windll.user32.SendMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM
]
ctypes.windll.user32.SendMessageW.restype = wintypes.LPARAM


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
        self.root = tk.Tk()
        self.root.withdraw()

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
        self.is_enabled = True

        # ステータス表示の位置モード
        # False = 右下固定
        # True  = マウス追従
        self.is_mouse_follow_enabled = False

        # 監視間隔
        self.mouse_follow_interval_ms = 30
        self.ime_watch_interval_ms = 200

        self.active_mode_key = "f13"
        self.last_ime_status = None

        # ステータス表示用オーバーレイ
        self.status_overlay = tk.Toplevel(self.root)
        self.status_overlay.overrideredirect(True)
        self.status_overlay.attributes("-topmost", True)
        self.status_overlay.attributes("-alpha", 0.75)

        self.status_label = tk.Label(
            self.status_overlay,
            text="BASE",
            font=("Meiryo", 11, "bold"),
            bg="white",
            fg="black",
            padx=10,
            pady=4
        )
        self.status_label.pack()

        # トレイメニュー
        self.setup_tray()
        self.ui_queue = ui_queue

        # 定期処理は最後に1回だけ登録
        self.root.after(50, process_queue)
        self.root.after(200, self.watch_ime_status)
        self.root.after(30, self.follow_mouse)

        # 初期位置
        self.place_status_overlay()

    def setup_tray(self):
        icon_img = self.create_menu_icon()
        menu = (
            item('写真表示 有効/無効', self.toggle_enabled, checked=lambda item: self.is_enabled),
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

    def toggle_enabled(self, icon, item):
        self.is_enabled = not self.is_enabled

        # 写真表示をOFFにしたときだけ、表示中の写真レイヤーを消す
        if not self.is_enabled:
            ui_queue.put(lambda: self.hide_layer("forced"))

    def toggle_mouse_follow(self, icon, item):
        self.is_mouse_follow_enabled = not self.is_mouse_follow_enabled

        # 切り替え直後に位置を更新
        ui_queue.put(lambda: self.place_status_overlay())


    def set_duration(self, icon, item):
        def ask():
            new_sec = simpledialog.askfloat("設定", "表示秒数を入力:",
                                            initialvalue=self.duration_ms / 1000,
                                            minvalue=0.1, maxvalue=60.0)
            if new_sec is not None:
                self.duration_ms = int(new_sec * 1000)
        self.root.after(0, ask)

    def quit_app(self, icon, item):
        self.icon.stop()
        self.root.after(0, self.root.destroy)

    def get_active_monitor(self):
        try:
            window = gw.getActiveWindow()
            if window:
                mid_x = window.left + window.width / 2
                mid_y = window.top + window.height / 2
                for m in get_monitors():
                    if m.x <= mid_x <= m.x + m.width and m.y <= mid_y <= m.y + m.height:
                        return m
        except:
            pass
        return get_monitors()[0]

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
            img = Image.open(img_path).convert("RGBA")
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

    def place_status_overlay(self):
        self.status_label.update_idletasks()

        w = self.status_label.winfo_reqwidth() + 8
        h = self.status_label.winfo_reqheight() + 4

        if self.is_mouse_follow_enabled:
            # マウス追従表示
            mouse_x = self.root.winfo_pointerx()
            mouse_y = self.root.winfo_pointery()

            offset_x = 18
            offset_y = 24

            x = mouse_x + offset_x
            y = mouse_y + offset_y

            target_monitor = None
            for m in get_monitors():
                if m.x <= mouse_x <= m.x + m.width and m.y <= mouse_y <= m.y + m.height:
                    target_monitor = m
                    break

            if target_monitor is None:
                target_monitor = get_monitors()[0]

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

        self.status_overlay.geometry(f"{w}x{h}+{x}+{y}")

    def follow_mouse(self):
        """
        追従ONのときだけ、ステータス表示をマウスに追従させる。
        写真表示の有効/無効とは独立。
        """
        try:
            if self.is_mouse_follow_enabled:
                self.place_status_overlay()
        except Exception as e:
            print(f"Mouse Follow Error: {e}")

        self.root.after(self.mouse_follow_interval_ms, self.follow_mouse)

    def update_mode_status(self, key_name, ime_status=None):
        key_lower = key_name.lower()

        # デフォルト色
        fg_color = "black"
        bg_color = "white"

        if key_lower not in MODE_NAMES:
            mode = "None"

        elif ime_status == "japanese":
            mode = MODE_NAMES_JP.get(key_lower, MODE_NAMES.get(key_lower, "None"))
            fg_color = "red"  # 日本語入力は赤字
            bg_color = "white"

        elif ime_status in ("half_romaji", "full_romaji", "off"):
            mode = MODE_NAMES.get(key_lower, "None")
            fg_color = "black"  # ローマ字・英数は黒字
            bg_color = "white"

        else:
            mode = MODE_NAMES.get(key_lower, "None") + "?"
            fg_color = "black"
            bg_color = "white"

        self.status_label.config(
            text=mode,
            fg=fg_color,
            bg=bg_color
        )

        self.status_overlay.config(bg=bg_color)
        self.place_status_overlay()

    def watch_ime_status(self):
        """
        IME状態は写真表示の有効/無効とは関係なく常に監視する。
        """
        try:
            ime_status = get_ime_input_status()

            if ime_status != self.last_ime_status:
                self.last_ime_status = ime_status
                self.update_mode_status(self.active_mode_key, ime_status)

        except Exception as e:
            print(f"IME Watch Error: {e}")

        self.root.after(self.ime_watch_interval_ms, self.watch_ime_status)


    def run(self):
        threading.Thread(target=self.icon.run, daemon=True).start()
        self.place_status_overlay()
        self.root.mainloop()


# グローバルインスタンス
overlay_app = LayerOverlay()


def on_press(key):
    try:
        if hasattr(key, 'name'):
            k = key.name
        elif hasattr(key, 'char') and key.char:
            k = key.char
        else:
            k = str(key).strip("'")

        now = time.time()

        # F13〜F24 判定
        is_target_f_key = k and k.lower().startswith('f') and \
                         k.lower()[1:].isdigit() and 13 <= int(k.lower()[1:]) <= 24

        # その他のキーが押されたらオーバーレイを消す
        if not is_target_f_key:
            ui_queue.put(lambda: overlay_app.hide_layer("forced"))
            return

        # Fキー（F13〜F24）の処理
        if overlay_app.current_key != k:
            overlay_app.current_key = k
            overlay_app.press_start_time = now

            ime_status = get_ime_input_status()
            overlay_app.active_mode_key = k.lower()
            overlay_app.last_ime_status = ime_status

            ui_queue.put(lambda k=k, ime_status=ime_status: (
                overlay_app.show_layer(k),
                overlay_app.update_mode_status(k, ime_status)
            ))

    except Exception as e:
        print(f"Error in on_press: {e}")


def on_release(key):
    try:
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
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    overlay_app.run()
