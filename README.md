# ZMK Layer Overlay

**ZMK Layer Overlay** は、自作キーボード（特に Charybdis や分割キーボード）のレイヤー操作を視覚的にサポートするツールです。
特定のキー（レイヤー切り替えキー）を押している間、PC画面上に現在のレイヤーのキーマップ画像をオーバーレイ表示します。

## 🌟 主な特徴

* **リアルタイム表示:** レイヤー切り替えキーを押した瞬間に画像を高速表示。
* **アクティブモニター追従:** 現在マウスカーソルがある、またはアクティブなウィンドウがあるモニターの中央に表示。
* **自動リサイズ:** モニターの解像度に合わせて、画像のアスペクト比を維持したまま最適化（画面の80%サイズ）。
* **背景透過対応:** 透過PNGまたは特定の背景色を指定することで、デスクトップの邪魔をせずにキーマップを確認可能。
* **ポータブル設計:** EXE化して配布可能。利用者は `layers` フォルダに画像を置くだけで利用できます。

---

## 🛠️ ZMK側の設定

ZMKでレイヤーを切り替える際、同時に PC が検知できる信号（F13〜F24など）を送信するマクロを設定します。

`keymap` ファイルに以下のようなマクロを定義してください。

```c
/ {
    macros {
        // レイヤー1へ切り替えつつ、F13を送信するマクロ
        mo_l1: mo_l1 {
            compatible = "zmk,behavior-macro";
            #binding-cells = <0>;
            wait-ms = <0>;
            tap-ms = <0>;
            bindings
                = <&macro_press &mo 1 &kp F13>
                , <&macro_pause_for_release>
                , <&macro_release &mo 1 &kp F13>;
        };
    };

    keymap {
        base_layer {
            bindings = <
                // 既存の &mo 1 を &mo_l1 に置き換え
                ... &mo_l1 ...
            >;
        };
    };
};
🚀 PC側のセットアップ
1. フォルダ構成
以下の構成でファイルを配置します。

.
├── layer_viewer.exe  (または .py スクリプト)
└── layers/           (画像格納フォルダ)
      ├── f13.png     (レイヤー1用)
      ├── f14.png     (レイヤー2用)
      └── ...
2. 画像の準備
layers フォルダの中に、ZMKで設定したキー名（f13.png など）で画像を保存します。

背景透過: 背景を透明にしたい場合は、透過PNGを使用するか、画像背景を #abcdef (スクリプト内指定色) で塗りつぶしてください。

📦 ビルド方法 (開発者向け)
Python環境で以下のライブラリをインストールし、PyInstallerでEXE化できます。

# 必要ライブラリのインストール
pip install screeninfo pygetwindow Pillow pynput

# EXE化 (コンソール非表示・1ファイルに集約)
pyinstaller --noconsole --onefile layer_viewer.py
📋 動作要件
OS: Windows 10 / 11

Keyboard: ZMKファームウェアを搭載したキーボード（Charybdis等）

🤝 ライセンス
このプロジェクトは MIT License のもとで公開されています。


---

### GitHub公開時のアドバイス
* **LICENSEファイルの作成:** MIT Licenseにする場合は、GitHubの「Add file」→「Create new file」から `LICENSE` と入力すると、テンプレートが選べて簡単です。
* **Releasesの活用:** 利用者がPython環境を構築しなくて済むよう、PyInstallerで作った `layer_viewer.exe` を [Releases](https://docs.github.com/ja/repositories/releasing-projects-on-github/about-releases) にアップロードしておくと非常に親切です。

GitHubへのアップロード手順や、その他の構成（`.gitignore` の作成など）についてもお手伝いが必要でし
