# original launcher — 仕様書

## 概要

Total Commander 互換のファイルマネージャー。Python 標準ライブラリのみで動作。
EXE 禁止環境（Windows）でも `python launcher.py` で起動できることが要件。

```
python launcher.py [左パネルパス] [右パネルパス]
```

設定は自動保存・読み込みされる（後述のポータブルモードを参照）。

---

## ファイル構成

```
launcher/
  launcher.py          メイン実装 (単一ファイル)
  start.pyw            コンソールなし起動用ラッパー
  create_shortcut.ps1  デスクトップショートカット作成スクリプト
  ロケットアイコン.png  アプリアイコン
  SPEC.md              本仕様書
  DEVLOG.md            開発ログ・バグ修正履歴
```

---

## アーキテクチャ

### クラス構成

| クラス | 役割 |
|---|---|
| `App(tk.Tk)` | メインウィンドウ。キーバインド・コマンド・メニュー管理 |
| `FilePanel(tk.Frame)` | 左右どちらかのパネル。ファイルリスト表示・操作 |
| `VenvSelectDialog` | VSCode起動時のvenv選択ダイアログ |
| `VenvBasesDialog` | venvベースパス設定ダイアログ |
| `_BaseDialog` | モーダルダイアログ基底クラス |
| `CopyMoveDialog` | F5コピー/F6移動ダイアログ |
| `RenameDialog` | Shift+F6リネームダイアログ |
| `MkdirDialog` | F7新規ディレクトリダイアログ |
| `FindDialog` | Alt+F7ファイル検索ダイアログ |
| `MultiRenameDialog` | Ctrl+M一括リネームダイアログ |
| `HotlistMenu` | Ctrl+Dホットリストポップアップメニュー (TC互換) |
| `HotlistAddDialog` | ホットリスト追加ダイアログ |
| `HotlistConfigDialog` | ホットリスト編集・並び替えダイアログ |

### パネル参照

```python
app.ap   # アクティブパネル (active panel)
app.ip   # 非アクティブパネル (inactive panel)
```

---

## FilePanel の内部構造

### 主要フィールド

| フィールド | 型 | 内容 |
|---|---|---|
| `path` | `Path` | 現在ディレクトリ |
| `entries` | `list[dict]` | 表示中エントリ (listdir結果をソート済) |
| `selected` | `set[int]` | Insertで選択済のエントリindex集合 |
| `sort_col` | `str` | ソートキー (`name`/`ext`/`size`/`date`) |
| `sort_rev` | `bool` | 逆順フラグ |
| `tabs` | `list[str]` | タブのパス一覧 |
| `cur_tab` | `int` | 現在のタブindex |
| `filter` | `str` | ファイルフィルター (例: `*.py`) |
| `history` | `list[str]` | ナビゲーション履歴 (Alt+Left/Right用) |

### エントリdict のキー

```python
{
    "name":   str,   # ファイル名
    "ext":    str,   # 拡張子 (ドットなし)
    "size":   int,   # バイト数 (-1 = ディレクトリ)
    "mtime":  float, # 更新日時 (Unix timestamp)
    "is_dir": bool,
    "is_link": bool,
    "path":   str,   # フルパス
}
```

### Treeview の列構成

```
#0      アイコン列 (PhotoImage、幅32px、show="tree headings"で表示)
name    名前 (220px、w-anchor、stretch=True)
ext     拡張子 (55px)
size    サイズ (80px、右寄せ)
date    更新日時 (120px)
attr    属性 (45px、TC準拠rahs形式)
```

### カーソル管理の仕組み

`selectmode="browse"` + `_set_cursor(iid)` で focus と selection を同期させる。

```python
def _set_cursor(self, iid):
    self.tree.focus(iid)
    self.tree.selection_set([iid])
    self.tree.see(iid)
```

`_populate()` でリフレッシュする際はスクロール位置を保持するため `see()` を呼ばずに復元する。

### 選択 (Insert) とカーソルの色の区別

| 状態 | 色 | 定義 |
|---|---|---|
| カーソル行 (selected状態) | 濃青 `#000080` | `s.map(..., background=[("selected", cursor_bg)])` |
| Insert選択行 (selタグ) | 濃赤 `#8B0000` | `tag_configure("sel", background=sel_bg)` |
| ディレクトリ | 文字色 濃青 `#000080` | `tag_configure("dir", foreground=dir_fg)` |

---

## カラー定義 (C dict)

```python
C = {
    "panel_bg":       "#FFFFFF",   # パネル背景
    "panel_fg":       "#000000",   # パネル文字
    "dir_fg":         "#000080",   # ディレクトリ文字色 (暗青)
    "file_fg":        "#000000",
    "link_fg":        "#008000",   # シンボリックリンク (緑)
    "sel_bg":         "#8B0000",   # Insert選択行背景 (濃赤)
    "sel_fg":         "#FFFFFF",
    "cursor_bg":      "#000080",   # カーソル行背景 (濃青)
    "cursor_fg":      "#FFFFFF",
    "hdr_bg":         "#D4D0C8",   # 非アクティブヘッダー背景
    "hdr_fg":         "#000000",
    "bar_bg":         "#D4D0C8",   # ツールバー等の背景
    "bar_fg":         "#000000",
    "fnbar_bg":       "#000080",   # ファンクションキーバー背景
    "fnbar_num":      "#FFFF00",   # Fキー番号色 (黄)
    "fnbar_lbl":      "#FFFFFF",   # Fキーラベル色
    "active_hdr":     "#000080",   # アクティブパネルヘッダー背景
    "active_hdr_fg":  "#FFFFFF",
    "inactive_hdr":   "#D4D0C8",   # 非アクティブパネルヘッダー背景
    "inactive_hdr_fg":"#000000",
    "mid_bg":         "#D4D0C8",   # パネル間ボタンバー背景
}
```

---

## アプリアイコン

`ロケットアイコン.png` を `tk.PhotoImage` で読み込み、`iconphoto(True, image)` で全ウィンドウに適用する。
参照を `self._app_icon` に保持しないとGCで消える。

---

## アイコン生成 (ファイルリスト用)

PIL/Pillowは使わず、`PhotoImage.put()` でピクセルを直接書き込む。

```python
def _make_pixmap(root, pixels):
    img = tk.PhotoImage(master=root, width=w, height=h)
    for y, row in enumerate(pixels):
        img.put("{" + " ".join(row) + "}", to=(0, y))
    return img
```

- `_icon_folder(root)` → 黄色いフォルダアイコン (16x16)
- `_icon_file(root)` → 白いファイルアイコン (16x16)

---

## Windows 固有の実装

### ファイル属性 (`fmt_attr`)

`GetFileAttributesW` で Windows 属性フラグを取得し TC 準拠の `rahs` 形式に変換する。

```python
r = "r" if fa & 0x01 else "-"   # READONLY
a = "a" if fa & 0x20 else "-"   # ARCHIVE
h = "h" if fa & 0x02 else "-"   # HIDDEN
s = "s" if fa & 0x04 else "-"   # SYSTEM
```

`os.access()` は使わない（`rw--` 固定になるため）。

### ごみ箱への削除 (`_send_to_trash`)

`SHFileOperationW` を ctypes で直接呼ぶ。
`pFrom` に `path + "\0\0"` (ダブルnull終端) が必要。

```python
op.fFlags = 0x0040 | 0x0010  # FOF_ALLOWUNDO | FOF_NOCONFIRMATION
```

### ドライブ列挙 (`get_drives`)

`GetLogicalDrives()` のビットマップから `A:`～`Z:` を生成する。

---

## UI レイアウト構築順序

`side="bottom"` で pack するウィジェットは、`fill="both" expand=True` より**先に** pack しなければならない。

```python
# 正しい順序 (App.__init__ 内)
self._build_toolbar()   # pack fill="x" (top)
self._build_fnbar()     # pack side="bottom" ← 先
self._build_cmdline()   # pack side="bottom" ← 先
self._build_panels()    # pack fill="both" expand=True ← 後
self._build_mid_buttons()
```

この順序を逆にすると fnbar/cmdline がパネルの下に隠れて見えなくなる。

---

## キーバインド

すべて `self.bind_all()` で登録。ただし、ダイアログが開いている間はパネル操作キーが漏れないよう、
すべての `ba()` 呼び出しに `_guarded` ラッパーを適用している。

```python
def ba(key, fn):
    def _guarded(event):
        try:
            if event.widget.winfo_toplevel() is not self: return
        except Exception: return
        return fn(event)
    self.bind_all(key, _guarded)
```

`Entry` / `Text` ウィジェットにフォーカスがある場合はパネル操作キーを無効にする。

```python
def _is_input(self, event):
    return isinstance(event.widget, (tk.Entry, tk.Text))
```

### 主要キー一覧

| キー | 動作 |
|---|---|
| F3 | 表示 (viewer) |
| F4 | 編集 (editor) |
| F5 | コピー |
| F6 | 移動/リネーム |
| F7 | 新規ディレクトリ (カレントディレクトリに作成) |
| F8 / Delete | 削除 (ごみ箱) |
| Shift+F4 | 新規ファイル作成・編集 |
| Shift+F5 | 同ディレクトリにコピー |
| Shift+F6 | リネーム |
| Alt+F5 | ZIP圧縮 |
| Alt+F7 | ファイル検索 |
| Tab | パネル切替 |
| Insert / Space | 選択トグル |
| Ctrl+A | 全選択 |
| Num+ / Num- | パターン選択/解除 |
| Num* | 選択反転 |
| Num/ | 保存選択を復元 |
| Alt+Num+ | 同拡張子を選択 |
| Ctrl+T | 新規タブ |
| Ctrl+W | タブを閉じる |
| Ctrl+Tab | 次タブ |
| Ctrl+U | 左右交換 |
| Ctrl+B | ブランチビュー |
| Ctrl+D | ホットリスト |
| Ctrl+M | 一括リネーム |
| Ctrl+R | 再読み込み |
| Ctrl+F1/F2 | 簡易/詳細表示 |
| Ctrl+F3〜F6 | ソート |
| Ctrl+S | クイックフィルター |
| Ctrl+Enter | VSCodeで開く |
| Alt+Left/Right | 戻る/進む |
| Alt+F10 | ディレクトリツリー |
| Alt+Enter | プロパティ |
| Alt+F1/F2 | ドライブ変更 |

---

## ホットリスト (Ctrl+D)

TC互換のポップアップメニューとして実装。`HotlistMenu` は `overrideredirect(True)` の Toplevel。

- **Ctrl+D**: ポップアップを表示（アクティブパネルの Treeview 左上に配置、画面端でクランプ）
- **↑↓ / Enter / Esc**: キーボード操作
- メニュー項目: 登録パスへ移動 / セパレーター / 「追加」「設定」
- **追加**: `HotlistAddDialog` — 名前とパスを入力。"ターゲットパネルも保存" チェックボックスあり
- **設定**: `HotlistConfigDialog` — 一覧表示・削除・上下移動 (Alt+↑↓)

設定データ形式:
```json
"hotlist": {
  "名前": "/path/to/dir",
  "名前2": {"path": "/path/a", "target": "/path/b"}
}
```

---

## VSCode 連携 (Ctrl+Enter)

選択中のファイル/ディレクトリを `code` コマンドで開く。

- `code` は `code.cmd` のため `subprocess.Popen(..., shell=True)` が必須
- ディレクトリを選択した場合かつ `venv_bases` が設定済みの場合:
  - `VenvSelectDialog` を表示し、仮想環境を選択できる
  - 選択すると `call activate.bat && code <dir>` を実行
  - "venvなしで開く" を選択した場合は通常起動

---

## venv 管理

### venvベースパス (`venv_bases`)

設定 → "venvベースパス設定" から編集。複数のディレクトリを登録可能。
各ベースディレクトリ直下のサブディレクトリを venv 候補として扱う。

### VenvSelectDialog

候補一覧: `name  [base_dir]` 形式で表示。
キーボード操作: ↑↓で移動、Enter で選択、Esc でキャンセル。

---

## コマンドライン

ウィンドウ下部の `>` プロンプト。

- `cd <path>` → パネルのディレクトリ移動
- `md <name>` / `mkdir <name>` → ディレクトリ作成
- `rd <name>` / `rmdir <name>` → ディレクトリ削除
- その他 → `subprocess.Popen(cmd, shell=True, cwd=<current>)` で実行

---

## 設定ファイル

### 場所の優先順位 (ポータブルモード)

1. スクリプトと同じフォルダの `launcher_tc.json` (ポータブルモード)
2. `%USERPROFILE%\.launcher_tc.json` (デフォルト)

設定 → "設定ファイルの場所を変更" からディレクトリを選択すると、
現在の設定をコピーして以降はそのフォルダを使用する。
Cドライブが定期削除される環境などで、USBや別ドライブに設定を保存する用途を想定。

### キー一覧

```json
{
  "left_path": "...",
  "right_path": "...",
  "editor": "notepad",
  "viewer": "notepad",
  "geometry": "1280x720",
  "show_cmdline": true,
  "show_fnbar": true,
  "show_hidden": true,
  "hotlist": {},
  "left_history": [],
  "right_history": [],
  "saved_selection": [],
  "venv_bases": []
}
```

終了時に現在のパス・ウィンドウサイズを自動保存する。

---

## パスバーの表示形式

```
C:\Users\foo\bar\*.*
```

ルートドライブ (`C:\`) はすでに `\` で終わっているため、`sep` の二重付与を防ぐ。

```python
sep = "" if p.endswith(("\\", "/")) else "\\"
self.path_var.set(f"{p}{sep}{self.filter}")
```

---

## 移植・配布

### 必要なファイル

- `launcher.py`
- `start.pyw`
- `create_shortcut.ps1`
- `ロケットアイコン.png`

### セットアップ手順

1. 上記ファイルを任意のフォルダにコピー
2. Python 3.x (tkinter付き) をインストール
3. PowerShell で `create_shortcut.ps1` を実行してデスクトップショートカットを作成

### 設定の移植

移植先で起動後、設定 → "設定ファイルの場所を変更" から保存先を指定する。
