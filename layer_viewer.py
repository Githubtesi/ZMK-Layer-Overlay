import os
import sys
import tkinter as tk
from tkinter import simpledialog
import threading
from pynput import keyboard
from PIL import Image, ImageTk, ImageDraw
import pygetwindow as gw
from screeninfo import get_monitors
import pystray
from pystray import MenuItem as item

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
        self.root.withdraw()  # メインウィンドウは隠しておく

        # オーバーレイ用のウィンドウ
        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-transparentcolor", TRANS_COLOR)
        self.overlay.config(bg=TRANS_COLOR)

        self.label = tk.Label(self.overlay, bg=TRANS_COLOR)
        self.label.pack()
        self.overlay.withdraw()

        self.current_key = None
        self.after_id = None

        # 設定値
        self.duration_ms = 800  # デフォルト4秒
        self.is_enabled = True  # 動作フラグ

        # システムトレイの初期化
        self.setup_tray()

    def setup_tray(self):
        """システムトレイアイコンの作成"""
        # アイコン画像がない場合のための簡易画像生成1
        icon_img = self.create_menu_icon()

        menu = (
            item('有効/無効', self.toggle_enabled, checked=lambda item: self.is_enabled),
            item('表示秒数の設定', self.set_duration),
            item('終了', self.quit_app)
        )
        self.icon = pystray.Icon("LayerOverlay", icon_img, "Layer Overlay Tool", menu)

    def create_menu_icon(self):
        """トレイ用のアイコン画像を生成（正方形に円）"""
        img = Image.new('RGB', (64, 64), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.ellipse((10, 10, 54, 54), fill=(0, 120, 215))
        return img

    def toggle_enabled(self, icon, item):
        self.is_enabled = not self.is_enabled
        if not self.is_enabled:
            self.overlay.withdraw()

    def set_duration(self, icon, item):
        """秒数設定ダイアログを表示"""

        # Tkinterのダイアログはメインスレッドで呼ぶ必要がある
        def ask():
            new_sec = simpledialog.askfloat("設定", "表示する秒数を入力してください:",
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

            # 設定された秒数で隠す
            self.after_id = self.root.after(self.duration_ms, self.hide_layer)

        except Exception as e:
            print(f"Error: {e}")

    def hide_layer(self):
        self.overlay.withdraw()
        self.after_id = None
        self.current_key = None

    def run(self):
        # トレイアイコンを別スレッドで開始
        threading.Thread(target=self.icon.run, daemon=True).start()
        self.root.mainloop()


overlay_app = LayerOverlay()


def on_press(key):
    try:
        if not overlay_app.is_enabled:
            return

        k = key.name if hasattr(key, 'name') else getattr(key, 'char', None)
        if k and overlay_app.current_key != k:
            overlay_app.current_key = k
            overlay_app.root.after(0, overlay_app.show_layer, k)
    except:
        pass


def on_release(key):
    k = key.name if hasattr(key, 'name') else getattr(key, 'char', None)
    if k == overlay_app.current_key:
        overlay_app.current_key = None

if __name__ == '__main__':
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    overlay_app.run()