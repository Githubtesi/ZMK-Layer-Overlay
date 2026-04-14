import ctypes
import os
import sys
import tkinter as tk
from tkinter import simpledialog
import threading
import time
from pynput import keyboard
from pynput.keyboard import Controller, KeyCode, Key  # Keyを追加
from PIL import Image, ImageTk, ImageDraw
import pygetwindow as gw
from screeninfo import get_monitors
import pystray
from pystray import MenuItem as item

# --- 設定項目 ---
SHIFT_THRESHOLD = 0.4
F13_HOLD_THRESHOLD = 0.2  # 0.2秒以上でShiftに切り替わり
VK_IME_ON = 0x16
VK_IME_OFF = 0x15

# キーボードコントローラーの初期化
kb_controller = Controller()


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

        # 状態管理変数
        self.current_key = None
        self.press_start_time = 0
        self.last_f13_time = 0
        self.after_id = None
        self.duration_ms = 800
        self.is_enabled = True

        # --- F13 Hold-Tap 用 ---
        self.f13_is_pressed = False
        self.f13_as_shift_active = False

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
            new_sec = simpledialog.askfloat("設定", "表示秒数を入力:",
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
            print(f"Error: {e}")

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


def check_f13_hold(start_time):
    """別スレッドでF13の長押しを監視する"""
    time.sleep(F13_HOLD_THRESHOLD)
    # 指定時間経過後、まだ押されていればShiftをONにする
    if overlay_app.f13_is_pressed and overlay_app.press_start_time == start_time:
        overlay_app.f13_as_shift_active = True
        kb_controller.press(Key.shift)
        print("[System] F13 Hold: Shift ON")


def on_press(key):
    try:
        if hasattr(key, 'name'):
            k = key.name
        elif hasattr(key, 'char') and key.char:
            k = key.char
        else:
            k = str(key).strip("'")

        now = time.time()

        # F13〜F24かどうかの判定
        is_target_f_key = False
        if k and k.lower().startswith('f'):
            try:
                f_num = int(k.lower().replace('f', ''))
                if 13 <= f_num <= 24:
                    is_target_f_key = True
            except ValueError:
                pass

        # --- 非表示判定 ---
        if not is_target_f_key and k not in ['shift', 'shift_l', 'shift_r']:
            if overlay_app.overlay.winfo_viewable():
                overlay_app.root.after(0, overlay_app.hide_layer, "forced")

        # --- F13 特殊処理 (Hold-Tap) ---
        if k == 'f13':
            if not overlay_app.f13_is_pressed:
                overlay_app.f13_is_pressed = True
                overlay_app.press_start_time = now
                # 長押し判定スレッド開始
                threading.Thread(target=check_f13_hold, args=(now,), daemon=True).start()

        # F15 IME OFF
        elif k == 'f15':
            set_ime_status(0)

        # シフトキー単体（F13由来でない通常シフト）
        elif k in ['shift', 'shift_l', 'shift_r']:
            if now - overlay_app.last_f13_time < SHIFT_THRESHOLD:
                set_ime_status(1)
                overlay_app.last_f13_time = 0

        # 画像表示
        if is_target_f_key and overlay_app.current_key != k:
            overlay_app.current_key = k
            if k != 'f13':  # F13は既に記録済み
                overlay_app.press_start_time = now
            overlay_app.root.after(0, overlay_app.show_layer, k)

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

        now = time.time()

        if k == 'f13':
            duration = now - overlay_app.press_start_time
            overlay_app.f13_is_pressed = False

            # Shiftとして動作中だった場合は解除
            if overlay_app.f13_as_shift_active:
                kb_controller.release(Key.shift)
                overlay_app.f13_as_shift_active = False
                print("[System] F13 Release: Shift OFF")

            # 短いタップだった場合のみ、IMEをOFFにし、F13+Shift判定用の時間を記録
            elif duration < F13_HOLD_THRESHOLD:
                set_ime_status(0)
                overlay_app.last_f13_time = now
                print("[System] F13 Tap: IME OFF")

            # 画像の非表示処理
            if duration >= 1.0:
                overlay_app.root.after(0, overlay_app.hide_layer, "forced")
            else:
                overlay_app.root.after(0, overlay_app.start_hide_timer)
            overlay_app.current_key = None

        elif k == overlay_app.current_key:
            elapsed = now - overlay_app.press_start_time
            overlay_app.current_key = None
            if elapsed >= 1.0:
                overlay_app.root.after(0, overlay_app.hide_layer, "forced")
            else:
                overlay_app.root.after(0, overlay_app.start_hide_timer)

    except Exception as e:
        print(f"Error in on_release: {e}")


if __name__ == '__main__':
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    overlay_app.run()
