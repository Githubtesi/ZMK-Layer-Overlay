Layer Overlay Cursor Mode v7

変更内容:
- 初期状態: 写真表示OFF、カーソル変更ON、状態ラベル表示ON、追従ON。
- 通常の矢印カーソルは変更しません。
- 文字入力欄で表示される I ビームカーソルだけを変更します。
- F13 + 英数/IME OFF: I 英語（黒）
- F13 + 日本語入力: I 日本語（赤）
- F15 + 英数/IME OFF: I 数字（黒）
- F15 + 日本語入力: I 数字（赤）
- F14 Mouse: Windows標準カーソルへ戻します。

実行:
python layer_overlay_cursor_mode_v7.py

カーソルが残った場合:
python restore_default_cursor.py


変更点 v7:
- Iビームカーソル画像を v6 の約90% サイズに縮小しました。
- 表示文字は v6 と同じです。
