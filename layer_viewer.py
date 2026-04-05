import ctypes
import os
import sys
import tkinter as tk
from tkinter import simpledialog
import threading
import time
from pynput import keyboard
from pynput.keyboard import Controller, KeyCode
from PIL import Image, ImageTk, ImageDraw
import pygetwindow as gw
from screeninfo import get_monitors
import pystray
from pystray import MenuItem as item

# --- 設定項目 ---
SHIFT_THRESHOLD = 0.4
VK_IME_ON  = 0x16  # 強制IME ON
VK_IME_OFF = 0x15  # 強制IME OFF
# --- Windows IME制御用の設定 ---
# 0 = オフ（直接入力）, 1 = オン（ひらがな）
def set_ime_status(mode):
    """Windows APIを使用してIMEの状態を直接書き換える"""
    try:
        # アクティブなウィンドウのハンドルを取得
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        # IME入力コンテキストを取得
        ime_hwnd = ctypes.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        # WM_IME_CONTROL (0x0283) を送信して状態を変更
        # IMC_SETOPENSTATUS (0x0006) を使用
        ctypes.windll.user32.SendMessageA(ime_hwnd, 0x0283, 0x0006, mode)
    except Exception as e:
        print(f"IME Control Error: {e}")

SHIFT_THRESHOLD = 0.4  # F13の後の有効時間

# パス設定
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
        self.current_key = None
        self.press_start_time = 0
        self.last_f13_time = 0
        self.after_id = None
        self.duration_ms = 800
        self.is_enabled = True
        self.setup_tray()

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
            self.root.after(0, self.hide_layer, "forced")

    def set_duration(self, icon, item):
        def ask():
            new_sec = simpledialog.askfloat("設定", "1秒未満の時に表示する秒数を入力してください:",
                                            initialvalue=self.duration_ms / 1000, minvalue=0.1, maxvalue=60.0)
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
        except Exception as e:
            print(f"Error showing image: {e}")

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

overlay_app = LayerOverlay()
kb_controller = Controller()

def set_ime_mode(mode):
    """IMEを強制的に切り替える関数"""
    code = VK_IME_ON if mode == "ZEN" else VK_IME_OFF
    kb_controller.press(KeyCode.from_vk(code))
    kb_controller.release(KeyCode.from_vk(code))

def send_ime_state(state):
    """IMEの状態を強制的に書き換える"""
    code = VK_IME_ON if state == "ZEN" else VK_IME_OFF
    kb_controller.press(KeyCode.from_vk(code))
    kb_controller.release(KeyCode.from_vk(code))


def on_press(key):
    try:
        # キー名の取得
        k = key.name if hasattr(key, 'name') else getattr(key, 'char', str(key))
        now = time.time()

        # --- ご要望のロジック ---

        # 1. F15 ➔ 強制的に半角英数 (IME OFF)
        if k == 'f15':
            print("[IME] F15: 強制OFF")
            set_ime_status(0)

        # 2. F13 ➔ 強制的に半角英数 (IME OFF) + 時刻記録
        elif k == 'f13':
            print("[IME] F13: 強制OFF + Shift待機")
            overlay_app.last_f13_time = now
            set_ime_status(0)

        # 3. F13直後のShift ➔ 強制的にひらがな入力 (IME ON)
        elif key in [keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r]:
            if now - overlay_app.last_f13_time < SHIFT_THRESHOLD:
                print("[IME] F13+Shift: 強制ONに上書き")
                set_ime_status(1)
                overlay_app.last_f13_time = 0  # リセット

        # 画像オーバーレイ（既存の処理）
        if k and overlay_app.current_key != k:
            overlay_app.current_key = k
            overlay_app.press_start_time = now
            overlay_app.root.after(0, overlay_app.show_layer, k)

    except Exception as e:
        print(f"Error: {e}")
        
def on_release(key):
    try:
        k = key.name if hasattr(key, 'name') else getattr(key, 'char', None)
        if k == overlay_app.current_key:
            elapsed = time.time() - overlay_app.press_start_time
            overlay_app.current_key = None
            if elapsed >= 1.0:
                overlay_app.root.after(0, overlay_app.hide_layer, "forced")
            else:
                overlay_app.root.after(0, overlay_app.start_hide_timer)
    except Exception:
        pass

if __name__ == '__main__':
    print("=== デバッグモード起動中 ===")
    print("キーを叩くとここに名前が表示されます。F13やF15を押してみてください。")
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    overlay_app.run()
