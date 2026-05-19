# original launcher — 開発ログ

## 目的・制約

- Total Commander (TC) 互換のファイルマネージャーを Python で作る
- **Python 標準ライブラリのみ** (PIL/Pillow 等の外部パッケージ禁止)
- EXE 化禁止。`python launcher.py` で起動する形式のみ
- Windows 11 で動作すること (Windowsファイル属性・ごみ箱連携を含む)

---

## 実装済み機能

- 左右2パネル構成
- ドライブバー (コンボボックス + 空き容量表示 + `\` / `..` ボタン)
- タブ (複数ディレクトリを管理、Ctrl+T/W/Tab)
- パスバー (直接編集可能、フィルター付き)
- ファイルリスト: 名前/拡張子/サイズ/日時/属性 列、アイコン付き
- ソート (列ヘッダークリック、Ctrl+F3〜F6)
- 選択操作 (Insert/Space、Num+/-/\*//、Alt+Num+/-)
- クイック検索 (文字キー入力で前方一致ジャンプ、1.5秒でリセット)
- F3表示 / F4編集 (設定エディタで変更可能)
- F5コピー / F6移動 (ダイアログで宛先確認)
- F7新規ディレクトリ (カレントディレクトリに作成)
- F8削除 → ごみ箱 (Windows: SHFileOperationW)
- Shift+F4 新規ファイル作成
- Shift+F5 同ディレクトリにコピー (リネームダイアログ)
- Shift+F6 リネーム
- Alt+F5 ZIP圧縮 (stdlib の zipfile 使用)
- Alt+F7 ファイル検索 (名前パターン＋テキスト検索、サブディレクトリ対応)
- Ctrl+M 一括リネーム (検索置換・正規表現・連番 [N] 対応)
- Ctrl+D ホットリスト (TC互換ポップアップ、追加・設定・上下並び替え対応)
- Ctrl+Enter VSCodeで開く (ディレクトリ選択時はvenv選択ダイアログ表示)
- Shift+F2 ディレクトリ比較
- Ctrl+B ブランチビュー (サブディレクトリを含む全ファイル一覧)
- Alt+F10 ディレクトリツリー (遅延ロード)
- Alt+F1/F2 ドライブ変更ダイアログ
- Ctrl+U 左右交換 / Ctrl+I ターゲット=ソース
- Alt+Left/Right ナビゲーション履歴
- ファンクションキーバー (画面下部、表示切替可)
- コマンドライン (cd/md/rd/任意コマンド、表示切替可)
- 右クリックコンテキストメニュー
- ツールバー
- プロパティ表示 (Alt+Enter)
- ZIP ブラウズ (Enter キーで内容を一時展開・表示)
- 隠しファイル表示切替
- 簡易/詳細表示切替 (Ctrl+F1/F2)
- クイックフィルター (Ctrl+S)
- cmd.exe / PowerShell を現在ディレクトリで起動
- ウィンドウサイズ・パス・設定の自動保存
- アプリアイコン (ロケットアイコン.png)
- 設定ファイルの保存場所変更 (ポータブルモード)
- venvベースパス設定 (VSCode起動時に仮想環境を選択・有効化)

---

## バグ修正履歴

### 1. Windows パス解析 (bash のバックスラッシュ問題)

**症状**: `python launcher.py C:\Users\...` を bash 経由で渡すとバックスラッシュが消える  
**原因**: bash がバックスラッシュをエスケープ文字として処理する  
**対策**: PowerShell から起動する (`python launcher.py 'C:\Users\...'`)

---

### 2. `fmt_attr` が全ファイル `rw--` を返す

**症状**: 属性列が `rw--` または意味不明な値  
**原因**: `os.access()` は読み書き可能かどうかを返すだけで TC の `rahs` フラグとは無関係  
**修正**: `GetFileAttributesW` で Windows ファイル属性ビットマップを取得する

```python
fa = ctypes.windll.kernel32.GetFileAttributesW(str(path))
r = "r" if fa & 0x01 else "-"   # READONLY (0x01)
a = "a" if fa & 0x20 else "-"   # ARCHIVE  (0x20)
h = "h" if fa & 0x02 else "-"   # HIDDEN   (0x02)
s = "s" if fa & 0x04 else "-"   # SYSTEM   (0x04)
```

---

### 3. ルートドライブで `C:\\*.*` のように `\` が二重になる

**症状**: `C:\` のパス表示が `C:\\*.*` になる  
**原因**: `str(Path("C:\\"))` が `C:\` (末尾に `\` あり) を返すのに、コードがさらに `\` を付加していた  
**修正**:

```python
sep = "" if p.endswith(("\\", "/")) else "\\"
self.path_var.set(f"{p}{sep}{self.filter}")
```

---

### 4. ctypes 構造体のフィールド型エラー

**症状**: `SHFileOperationW` 呼び出しで `TypeError`  
**原因**: `hwnd` フィールドの型指定が不正だった  
**修正**: `ctypes.c_void_p` を使用する

```python
_fields_ = [("hwnd", ctypes.c_void_p), ...]
```

---

### 5. テンキーがダイアログの Entry 内でも発火する

**症状**: `Num+` でパターン選択ダイアログが開いている最中に再びダイアログが開く  
**原因**: `bind_all` で登録したためすべてのウィジェットで発火する  
**修正**: `_noentry()` ラッパーで Entry/Text フォーカス中は無視する

```python
def _noentry(fn): return lambda e: None if self._is_input(e) else fn()
ba("<KP_Add>", _noentry(lambda: self.ap.select_by_pattern(True)))
```

---

### 6. タブラベルがナビゲーション後に更新されない

**症状**: ディレクトリを移動してもタブに表示されるパスが古いまま  
**原因**: `goto()` が `self.tabs[self.cur_tab]` を更新しておらず、`_build_tabbar()` も呼ばれていなかった  
**修正**: `goto()` 内で両方を実行する

```python
self.tabs[self.cur_tab] = p
self._build_tabbar()
```

---

### 7. フォルダ・ファイルアイコンが表示されない

**症状**: `#0` 列が幅0で見えない、アイコンが消える  
**原因**: `show="headings"` では `#0` (ツリー) 列が非表示になる  
**修正**: `show="tree headings"` に変更し、`#0` 列の幅と設定を明示する

```python
self.tree = ttk.Treeview(..., show="tree headings", ...)
self.tree.column("#0", width=32, stretch=False, minwidth=32)
self.tree.heading("#0", text="")
```

---

### 8. コマンドライン・ファンクションキーバーが見えない

**症状**: 画面下部のコマンドラインとFキーバーが表示されない  
**原因**: `pack(fill="both", expand=True)` のパネルコンテナを先に pack してから `side="bottom"` のウィジェットを pack すると、後者が押しつぶされて見えなくなる  
**修正**: `side="bottom"` のウィジェットを**必ず先に** pack する

```python
# 正しい順序
self._build_fnbar()     # side="bottom" ← 先
self._build_cmdline()   # side="bottom" ← 先
self._build_panels()    # expand=True   ← 後
```

---

### 9. カーソル行が白背景と同化して見えない

**症状**: カーソルがある行が白く塗り潰されて見分けがつかない  
**原因 (2段階)**:

1. `selectmode="none"` → Treeview の `selected` 状態が設定されない → `s.map(background=[("selected", cursor_bg)])` が効かない
2. `selected` 状態がないので、`tree.focus()` で移動しても色変化なし → デフォルトの白/グレーのまま

**修正**:

```python
self.tree = ttk.Treeview(..., selectmode="browse", ...)

def _set_cursor(self, iid):
    self.tree.focus(iid)
    self.tree.selection_set([iid])
    self.tree.see(iid)

s.map(n,
    background=[("selected", C["cursor_bg"])],
    foreground=[("selected", C["cursor_fg"])])
```

---

### 10. アイコン列と名前が重なる

**症状**: `#0` 列の幅が小さく、フォルダアイコンとファイル名が重なって見える  
**原因**: 初期値20pxではMeiryo UIフォントのアイコンに対して幅不足  
**修正**: `#0` 列の幅を32pxに変更

```python
self.tree.column("#0", width=32, stretch=False, minwidth=32)
```

---

### 11. F7 新規ディレクトリがカレントでなく選択フォルダ内に作られる

**症状**: フォルダにカーソルがある状態でF7を押すと、そのフォルダの中に作成される  
**原因**: `cmd_mkdir()` がダイアログを開いた後に `self.ap.path` を参照していたが、Enterキーの漏れ (`bind_all("<Return>")`) によりダイアログの確定と同時にカーソル下のフォルダへ遷移し、その後 `goto()` した先に作成されていた  
**修正1**: `target_dir = panel.path` でパスをダイアログ表示前にスナップショット取得  
**修正2**: ダイアログの `<Return>` バインドで `"break"` を返しイベント伝播を止める  
**修正3**: 全 `ba()` 呼び出しに `_guarded` ラッパーを適用し、ダイアログ所有ウィンドウ以外ではキーを無視

---

### 12. コピー/移動後にファイルが開く

**症状**: F5/F6 ダイアログで確定後、コピー先のファイルが開いてしまう  
**原因**: ダイアログの Enter がリークして `_key_enter()` → `open_file()` が発火  
**修正**: 11 と同じ `_guarded` ラッパーで対応

---

### 13. 削除・新規作成後にスクロールが先頭に戻る

**症状**: ファイル削除やディレクトリ作成後、パネルの表示が一番上にスクロールされる  
**原因**: `_populate()` 内で `_set_cursor()` → `see()` が呼ばれ、常にカーソル行が見える位置に移動していた  
**修正**: リフレッシュ時はスクロール位置を保存・復元し、`see()` を呼ばない

```python
scroll = self.tree.yview()[0]
# ... rebuild tree ...
self.tree.focus(target_iid)
self.tree.selection_set([target_iid])
self.tree.yview_moveto(scroll)   # see() は呼ばない
```

---

### 14. アクティブパネルのヘッダー行まで青くなる

**症状**: アクティブパネル切替時に列ヘッダー (名前/拡張子/サイズ...) まで青背景になる  
**原因**: `set_active()` が ttk スタイルのヘッダー色を変更していた  
**修正**: `set_active()` でヘッダー色は変更せず、`selection_set` の管理のみ行う。ヘッダー色は常に固定。

---

### 15. VSCode が見つからないエラー

**症状**: "VSCodeが見つかりません" エラーが出る  
**原因**: `code` コマンドの実体は `code.cmd` であり、`subprocess.Popen(["code", ...])` では `.cmd` を見つけられない  
**修正**: `shell=True` を使用する

```python
subprocess.Popen(cmd, shell=True)
```

---

### 16. venv 選択ダイアログのキー操作がパネルに漏れる

**症状**: `VenvSelectDialog` 内でカーソルキーを押すとパネルのカーソルが動く  
**原因**: `bind_all("<Up>/<Down>")` が全ウィジェットに発火する。`_is_input()` は `Entry`/`Text` のみをチェックし `Listbox` は対象外  
**修正**: 全 `ba()` 呼び出しに `_guarded` ラッパーを適用。ダイアログが開いている間はパネルのキーバインドが無効になる

---

### 17. Listbox の選択状態が青くならない

**症状**: `VenvSelectDialog` の Listbox でフォーカスを失うと選択が消える  
**原因**: `exportselection=True` (デフォルト) により、他ウィジェットがフォーカスを持つと Listbox の選択がクリアされる  
**修正**: `exportselection=False` を設定し、`selectbackground`/`selectforeground` を明示指定

---

### 18. Listbox のキー移動で選択ハイライトが追従しない

**症状**: ↑↓キーで移動してもハイライトが追従しない  
**原因**: Listbox の ↑↓ キーは "active" 位置を動かすが "selection" は動かさない  
**修正**: `<Up>`/`<Down>` にバインドして `after(0, _sync_sel)` で selection を active に同期

```python
def _sync_sel():
    idx = lb.index(tk.ACTIVE)
    lb.selection_clear(0, tk.END)
    lb.selection_set(idx)
lb.bind("<Up>", lambda e: lb.after(0, _sync_sel))
lb.bind("<Down>", lambda e: lb.after(0, _sync_sel))
```

---

### 19. create_shortcut.ps1 の文字化けと構文エラー

**症状**: PowerShell で実行すると文字化けするか構文エラーで動かない  
**原因**: ファイルが UTF-8 (BOMなし) で保存されているが、Windows PowerShell のデフォルトエンコーディングは CP932。日本語文字列と `✓` 記号が誤って解釈された  
**修正**: ファイル全体を純粋なASCIIで書き直し。日本語コメント・メッセージをすべて英語に置き換え

---

## 既知の制限・未実装

- 属性変更 (READONLY/HIDDEN 等の書き込み) は未実装。OS の機能を使うよう案内のみ
- Ctrl+V によるクリップボードからのファイルペーストは未実装
- ZIP 以外のアーカイブ (7z, RAR 等) はサポートしない
- F3 ビューアは外部エディタを起動するだけ (インライン Lister は非対応)
- FTP 接続は未対応
- ファイル転送の進捗バーなし (タイトルバーにファイル名を表示するのみ)
