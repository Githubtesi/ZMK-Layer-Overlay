import os
import sys
import tkinter as tk
from pynput import keyboard
from PIL import Image, ImageTk
import pygetwindow as gw
from screeninfo import get_monitors

# パス設定
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_FOLDER = os.path.join(BASE_DIR, "layers")
TRANS_COLOR = "#abcdef"  # 透過させるためのキーカラー（画像に使わない色を指定）


class LayerOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANS_COLOR)  # 指定色を透明化
        self.root.config(bg=TRANS_COLOR)

        self.label = tk.Label(self.root, bg=TRANS_COLOR)
        self.label.pack()
        self.root.withdraw()
        self.current_key = None

    def get_active_monitor(self):
        """現在アクティブなウィンドウがあるモニターを特定する"""
        try:
            window = gw.getActiveWindow()
            if window:
                # ウィンドウの中心座標を取得
                mid_x = window.left + window.width / 2
                mid_y = window.top + window.height / 2
                for m in get_monitors():
                    if m.x <= mid_x <= m.x + m.width and m.y <= mid_y <= m.y + m.height:
                        return m
        except:
            pass
        return get_monitors()[0]  # 取得失敗時はメインモニター

    def show_layer(self, key_name):
        img_path = os.path.join(IMAGE_FOLDER, f"{key_name.lower()}.png")
        if not os.path.exists(img_path):
            return

        monitor = self.get_active_monitor()

        try:
            # 画像の読み込みとリサイズ
            img = Image.open(img_path).convert("RGBA")

            # モニターサイズに収まるようにリサイズ（画面の80%程度にする例）
            max_w, max_h = int(monitor.width * 0.8), int(monitor.height * 0.8)
            img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

            self.photo = ImageTk.PhotoImage(img)
            self.label.config(image=self.photo)

            # 表示位置をモニターの中央に計算
            x = monitor.x + (monitor.width - img.width) // 2
            y = monitor.y + (monitor.height - img.height) // 2

            self.root.geometry(f"{img.width}x{img.height}+{x}+{y}")
            self.root.deiconify()
        except Exception as e:
            print(f"Error: {e}")

    def hide_layer(self):
        self.root.withdraw()


overlay = LayerOverlay()


def on_press(key):
    try:
        k = key.name if hasattr(key, 'name') else None
        if k and overlay.current_key != k:
            overlay.current_key = k
            overlay.show_layer(k)
    except:
        pass


def on_release(key):
    k = key.name if hasattr(key, 'name') else None
    if k == overlay.current_key:
        overlay.current_key = None
        overlay.hide_layer()


listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()
overlay.root.mainloop()