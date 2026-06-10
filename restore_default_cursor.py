import ctypes
from ctypes import wintypes

SPI_SETCURSORS = 0x0057
SPIF_SENDCHANGE = 0x0002

user32 = ctypes.windll.user32
user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    wintypes.UINT,
]
user32.SystemParametersInfoW.restype = wintypes.BOOL

ok = user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_SENDCHANGE)
print("カーソルを標準状態へ戻しました。" if ok else "カーソル復旧に失敗しました。")
