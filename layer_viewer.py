import ctypes
import os
import sys
import tkinter as tk
from tkinter import simpledialog
import threading
import time
import queue

from pynput import keyboard
from PIL import Image, ImageTk, ImageDraw
import pygetwindow as gw
from screeninfo import get_monitors
import pystray
from pystray import MenuItem as item

# --- 設定項目 ---
DURATION_MS = 800          # オーバーレイ表示時間（ms）

# キュー（スレッド間安全通信用）
ui_queue = queue.Queue()

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
        hwnd = ctypes.windll.user32.GetForegroundWindow()
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


class LayerOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
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
        self.is_enabled = True

        self.setup_tray()
        self.ui_queue = ui_queue
        self.root.after(50, process_queue)

    def setup_tray(self):
        icon_img = self.create_menu_icon()
        menu = (
            item('有効/無効', self.toggle_enabled, checked=lambda item: self.is_enabled),
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
        if not self.is_enabled:
            ui_queue.put(lambda: self.hide_layer("forced"))

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

    def run(self):
        threading.Thread(target=self.icon.run, daemon=True).start()
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
            if overlay_app.overlay.winfo_viewable():
                ui_queue.put(lambda: overlay_app.hide_layer("forced"))
            return

        # Fキー（F13〜F24）の処理
        if overlay_app.current_key != k:
            overlay_app.current_key = k
            overlay_app.press_start_time = now
            ui_queue.put(lambda: overlay_app.show_layer(k))

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
