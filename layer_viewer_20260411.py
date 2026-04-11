import ctypes
import os
import sys
import tkinter as tk
from tkinter import simpledialog
import threading
import time
from pynput import keyboard
from pynput.keyboard import Controller, KeyCode, Key
from PIL import Image, ImageTk, ImageDraw
import pygetwindow as gw
from screeninfo import get_monitors
import pystray
from pystray import MenuItem as item

# --- 設定項目 ---
SHIFT_THRESHOLD = 0.4
VK_IME_ON = 0x16   # 強制IME ON
VK_IME_OFF = 0x15  # 強制IME OFF

# --- Windows IME制御 ---
def set_ime_status(mode):
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        ime_hwnd = ctypes.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        ctypes.windll.user32.SendMessageA(ime_hwnd, 0x0283, 0x0006, mode)
    except Exception as e:
        print(f"IME Control Error: {e}")


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
            new_sec = simpledialog.askfloat("設定", "表示秒数を入力してください（0.1〜60秒）:",
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
            print(f"画像が見つかりません: {img_path}")
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
            print(f"[Overlay] 表示: {key_name}")
        except Exception as e:
            print(f"Error showing image: {e}")

    def hide_layer(self, called_id="forced"):
        if called_id == "forced" or called_id == self.after_id:
            self.overlay.withdraw()
            self.after_id = None
            print("[Overlay] 非表示")

    def hide_immediately(self):
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.root.after(0, self.hide_layer, "forced")

    def run(self):
        threading.Thread(target=self.icon.run, daemon=True).start()
        self.root.mainloop()


# --------------------------------------------------
overlay_app = LayerOverlay()
kb_controller = Controller()

# F13が押されているかどうかの状態管理
f13_held = False


def on_press(key):
    global f13_held
    try:
        k = key.name if hasattr(key, 'name') else getattr(key, 'char', str(key))
        now = time.time()

        # ==================== F13 処理 ====================
        if k == 'f13':
            if not f13_held:                     # 初めて押されたときだけ
                print("[F13] 押下 → Shiftをホールド開始")
                kb_controller.press(Key.shift)   # Shiftを押し続ける
                f13_held = True

            # IME強制OFF + 画像表示
            print("[IME] F13: 強制OFF")
            set_ime_status(0)
            overlay_app.last_f13_time = now

            # 画像表示
            overlay_app.current_key = k
            overlay_app.press_start_time = now
            overlay_app.root.after(0, overlay_app.show_layer, k)

        # F13直後の物理Shift → ひらがな（IME ON）
        elif key in [Key.shift, Key.shift_l, Key.shift_r]:
            if now - overlay_app.last_f13_time < SHIFT_THRESHOLD:
                print("[IME] F13+Shift: 強制ON")
                set_ime_status(1)
                overlay_app.last_f13_time = 0

        # ==================== その他のキー ====================
        else:
            # F13以外が押されたら画像を即非表示
            if overlay_app.overlay.state() != 'withdrawn':
                print(f"[Overlay] 任意キー '{k}' 押下 → 画像を非表示")
                overlay_app.hide_immediately()

    except Exception as e:
        print(f"Error in on_press: {e}")


def on_release(key):
    global f13_held
    try:
        k = key.name if hasattr(key, 'name') else getattr(key, 'char', None)

        # F13が離されたらShiftも離す
        if k == 'f13' and f13_held:
            print("[F13] 離された → Shiftホールド解除")
            kb_controller.release(Key.shift)
            f13_held = False

        # 画像の自動非表示処理（従来通り）
        if k == overlay_app.current_key:
            elapsed = time.time() - overlay_app.press_start_time
            overlay_app.current_key = None
            if elapsed >= 1.0:
                overlay_app.root.after(0, overlay_app.hide_layer, "forced")
            else:
                overlay_app.root.after(0, overlay_app.start_hide_timer)  # start_hide_timerはクラスに定義済み

    except Exception as e:
        print(f"Error in on_release: {e}")


if __name__ == '__main__':
    print("=== Layer Overlay Tool 起動中 ===")
    print("F13を押している間、Shiftキーが仮想的にホールドされます")
    print("F13〜F24 で画像表示 / その他のキーで即非表示")
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    overlay_app.run()