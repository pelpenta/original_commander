#!/usr/bin/env python3
"""
original launcher - Total Commander 互換ファイルマネージャー (Python製)
使用方法: python launcher.py [左パネルパス] [右パネルパス]
依存ライブラリ: 標準ライブラリのみ (tkinter)
"""
import os, sys, shutil, stat, subprocess, string, time, json, re, zipfile, fnmatch
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ── 設定 ────────────────────────────────────────────
APP_NAME = "original launcher"

# 設定ファイルの優先順位:
#   1. スクリプトと同じフォルダの launcher_tc.json (ポータブルモード)
#   2. %USERPROFILE%\.launcher_tc.json (デフォルト)
_SCRIPT_DIR = Path(__file__).resolve().parent
_LOCAL_CFG  = _SCRIPT_DIR / "launcher_tc.json"
_HOME_CFG   = Path.home() / ".launcher_tc.json"
CONFIG_FILE = _LOCAL_CFG if _LOCAL_CFG.exists() else _HOME_CFG
DEFAULT_CFG = {
    "left_path": str(Path.home()),
    "right_path": str(Path.home()),
    "editor": "notepad",
    "viewer": "notepad",
    "geometry": "1280x720",
    "show_cmdline": True,
    "show_fnbar": True,
    "show_hidden": True,
    "hotlist": {},          # name -> path
    "left_history": [],
    "right_history": [],
    "saved_selection": [],
    "venv_bases": [],
}

def load_cfg():
    try:
        if CONFIG_FILE.exists():
            d = DEFAULT_CFG.copy()
            d.update(json.loads(CONFIG_FILE.read_text("utf-8")))
            return d
    except Exception:
        pass
    return DEFAULT_CFG.copy()

def save_cfg(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass

# ── ファイル情報ユーティリティ ────────────────────────
def fmt_size(n):
    if n < 0: return "<DIR>"
    for unit, div in [("", 1), ("K", 1024), ("M", 1024**2), ("G", 1024**3), ("T", 1024**4)]:
        if n < div * 1024 or unit == "T":
            if unit == "": return f"{n:,}"
            return f"{n/div:.1f}{unit}"

def fmt_date(ts):
    try: return datetime.fromtimestamp(ts).strftime("%Y/%m/%d %H:%M")
    except: return ""

def _send_to_trash(path):
    """Windows: ごみ箱へ移動"""
    if sys.platform == "win32":
        import ctypes
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint),
                        ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                        ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
        op = SHFILEOPSTRUCTW()
        op.hwnd = None; op.wFunc = 3  # FO_DELETE
        op.pFrom = path + "\0\0"
        op.fFlags = 0x0040 | 0x0010  # FOF_ALLOWUNDO | FOF_NOCONFIRMATION
        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if ret != 0: raise OSError(f"ごみ箱移動エラー: {ret}")
    else:
        p = Path(path)
        shutil.rmtree(str(p)) if p.is_dir() else p.unlink()

def fmt_attr(path):
    """TC準拠: rahs (読取専用/アーカイブ/隠し/システム)"""
    try:
        if sys.platform == "win32":
            import ctypes
            fa = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if fa == -1: return "----"
            r = "r" if fa & 0x01 else "-"   # READONLY
            a = "a" if fa & 0x20 else "-"   # ARCHIVE
            h = "h" if fa & 0x02 else "-"   # HIDDEN
            s = "s" if fa & 0x04 else "-"   # SYSTEM
            return r + a + h + s
        else:
            ro = not os.access(path, os.W_OK)
            return ("r" if ro else "-") + "---"
    except: return "----"

def disk_free(path):
    try:
        u = shutil.disk_usage(path)
        return u.free // 1024, u.total // 1024
    except: return 0, 0

def list_dir(path, show_hidden=True):
    entries = []
    try:
        for e in os.scandir(path):
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                is_link = e.is_symlink()
                st = e.stat(follow_symlinks=False)
                if not show_hidden:
                    if sys.platform == "win32":
                        import ctypes
                        fa = ctypes.windll.kernel32.GetFileAttributesW(e.path)
                        if fa != -1 and (fa & 0x02): continue
                    elif e.name.startswith("."): continue
                ext = "" if is_dir else Path(e.name).suffix.lstrip(".")
                entries.append({
                    "name": e.name, "ext": ext,
                    "size": -1 if is_dir else st.st_size,
                    "mtime": st.st_mtime,
                    "is_dir": is_dir, "is_link": is_link,
                    "path": e.path,
                })
            except: pass
    except PermissionError: pass
    return entries

def sort_entries(entries, col="name", rev=False):
    dirs  = [e for e in entries if e["is_dir"]]
    files = [e for e in entries if not e["is_dir"]]
    key = {"name": lambda e: e["name"].lower(),
           "ext":  lambda e: (e["ext"].lower(), e["name"].lower()),
           "size": lambda e: e["size"],
           "date": lambda e: e["mtime"]}.get(col, lambda e: e["name"].lower())
    dirs.sort(key=key, reverse=rev)
    files.sort(key=key, reverse=rev)
    return dirs + files

def get_drives():
    if sys.platform != "win32": return ["/"]
    import ctypes
    bm = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{c}:" for i, c in enumerate(string.ascii_uppercase) if bm & (1 << i)]

def open_file(path):
    try:
        if sys.platform == "win32": os.startfile(str(path))
        elif sys.platform == "darwin": subprocess.Popen(["open", str(path)])
        else: subprocess.Popen(["xdg-open", str(path)])
    except Exception as ex:
        messagebox.showerror("エラー", str(ex))

# ── カラー定義 ──────────────────────────────────────
# TC デフォルト (クラシック) カラー - 白地・黒文字 + TC強調色
C = {
    "panel_bg":    "#FFFFFF",
    "panel_fg":    "#000000",
    "dir_fg":      "#000080",   # 暗青 = ディレクトリ
    "file_fg":     "#000000",
    "link_fg":     "#008000",
    "sel_bg":      "#8B0000",   # Insert選択行: 濃赤
    "sel_fg":      "#FFFFFF",
    "cursor_bg":   "#000080",   # カーソル行: 濃青
    "cursor_fg":   "#FFFFFF",
    "hdr_bg":      "#D4D0C8",
    "hdr_fg":      "#000000",
    "bar_bg":      "#D4D0C8",
    "bar_fg":      "#000000",
    "fnbar_bg":    "#000080",
    "fnbar_num":   "#FFFF00",
    "fnbar_lbl":   "#FFFFFF",
    "drive_bg":    "#D4D0C8",
    "path_bg":     "#FFFFFF",
    "path_fg":     "#000000",
    "active_hdr":  "#000080",   # アクティブパネルのヘッダー背景
    "active_hdr_fg": "#FFFFFF",
    "inactive_hdr":  "#D4D0C8",
    "inactive_hdr_fg": "#000000",
    "mid_bg":      "#D4D0C8",   # パネル間ボタンバー
}

def _make_pixmap(root, pixels):
    """ピクセルリスト(行×列のカラーリスト)からPhotoImageを生成"""
    h, w = len(pixels), len(pixels[0])
    img = tk.PhotoImage(master=root, width=w, height=h)
    for y, row in enumerate(pixels):
        img.put("{" + " ".join(row) + "}", to=(0, y))
    return img

def _icon_folder(root):
    _ = C["panel_bg"];  F = "#FFB900"; D = "#C87800"; L = "#FFD050"
    p = [
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
        [_,D,D,D,D,_,_,_,_,_,_,_,_,_,_,_],
        [_,D,L,L,D,D,D,D,D,D,D,D,D,D,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,F,F,F,F,F,F,F,F,F,F,F,F,D,_],
        [_,D,D,D,D,D,D,D,D,D,D,D,D,D,D,_],
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
    ]
    return _make_pixmap(root, p)

def _icon_file(root):
    _ = C["panel_bg"];  W = "#FFFFFF"; G = "#808080"; B = "#C0C0C0"
    p = [
        [_,_,W,W,W,W,W,W,W,W,W,W,_,_,_,_],
        [_,_,W,B,B,B,B,B,B,W,G,W,_,_,_,_],
        [_,_,W,B,B,B,B,B,W,G,W,W,_,_,_,_],
        [_,_,W,B,B,B,B,W,G,W,W,W,_,_,_,_],
        [_,_,W,G,G,G,G,G,W,W,W,W,_,_,_,_],
        [_,_,W,W,W,W,W,W,W,W,W,W,_,_,_,_],
        [_,_,W,G,G,G,G,G,G,G,G,W,_,_,_,_],
        [_,_,W,G,G,G,G,G,G,G,G,W,_,_,_,_],
        [_,_,W,G,G,G,G,G,G,G,G,W,_,_,_,_],
        [_,_,W,G,G,G,G,G,G,G,G,W,_,_,_,_],
        [_,_,W,G,G,G,G,G,G,G,G,W,_,_,_,_],
        [_,_,W,G,G,G,G,G,G,G,G,W,_,_,_,_],
        [_,_,W,W,W,W,W,W,W,W,W,W,_,_,_,_],
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
        [_,_,_,_,_,_,_,_,_,_,_,_,_,_,_,_],
    ]
    return _make_pixmap(root, p)

# ── ファイルパネル ──────────────────────────────────
class FilePanel(tk.Frame):
    COLS = [
        ("name", "名前",      220, "w"),
        ("ext",  "拡張子",     55, "w"),
        ("size", "サイズ",     80, "e"),
        ("date", "更新日時",  120, "w"),
        ("attr", "属性",       45, "w"),
    ]

    def __init__(self, master, app, side, init_path):
        super().__init__(master, bg=C["panel_bg"])
        self.app  = app
        self.side = side          # "left" / "right"
        self.path = Path(init_path).resolve()
        self.entries   = []       # 現在表示中のエントリ
        self.selected  = set()    # 選択済みindex
        self.saved_sel = []       # Num/ で保存した選択
        self.sort_col  = "name"
        self.sort_rev  = False
        self.history   = []
        self.hist_pos  = -1
        self.tabs      = [str(self.path)]
        self.cur_tab   = 0
        self.filter    = "*.*"
        self.q_str     = ""       # クイック検索文字列
        self.q_timer   = None
        self.brief_mode = False   # False=Full, True=Brief
        self.icon_folder = None   # 初回buildで初期化
        self.icon_file   = None
        self._build()
        self.refresh()

    # ── UI構築 ──
    def _build(self):
        # ドライブバー
        self.drive_frame = tk.Frame(self, bg=C["bar_bg"])
        self.drive_frame.pack(fill="x")
        self._build_drivebar()

        # タブバー
        self.tab_frame = tk.Frame(self, bg=C["bar_bg"])
        self.tab_frame.pack(fill="x")
        self._build_tabbar()

        # パスバー
        path_row = tk.Frame(self, bg=C["bar_bg"])
        path_row.pack(fill="x")
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(path_row, textvariable=self.path_var,
            bg=C["path_bg"], fg=C["path_fg"],
            font=("Meiryo UI", 9), relief="sunken", bd=1,
            insertbackground=C["path_fg"])
        self.path_entry.pack(side="left", fill="x", expand=True, padx=2, pady=1)
        self.path_entry.bind("<Return>", self._path_enter)
        self.filter_btn = tk.Button(path_row, text="*", width=2,
            bg=C["bar_bg"], font=("Meiryo UI", 8),
            command=self._change_filter, relief="flat")
        self.filter_btn.pack(side="left")

        # ファイルリスト
        list_frame = tk.Frame(self, bg=C["panel_bg"])
        list_frame.pack(fill="both", expand=True)

        self._setup_style()
        # アイコン初期化 (初回のみ)
        if self.icon_folder is None:
            self.icon_folder = _icon_folder(self)
            self.icon_file   = _icon_file(self)
        cols = [c[0] for c in self.COLS]
        self.tree = ttk.Treeview(list_frame, columns=cols,
            show="tree headings", selectmode="browse",
            style=f"TC{self.side}.Treeview")
        # #0列はアイコン専用 (幅20、ストレッチなし、ヘッダーなし)
        self.tree.column("#0", width=32, stretch=False, minwidth=32)
        self.tree.heading("#0", text="")
        for col, label, width, anchor in self.COLS:
            self.tree.heading(col, text=label,
                command=lambda c=col: self._click_header(c))
            self.tree.column(col, width=width, anchor=anchor,
                stretch=(col == "name"), minwidth=30)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)

        # ステータス行
        self.stat_var = tk.StringVar()
        tk.Label(self, textvariable=self.stat_var,
            bg=C["bar_bg"], fg=C["bar_fg"],
            font=("Meiryo UI", 8), anchor="w"
        ).pack(fill="x")

        # イベント
        self.tree.bind("<Double-Button-1>", self._dbl_click)
        self.tree.bind("<Button-1>",        self._click)
        self.tree.bind("<Button-3>",        self._right_click)
        self.tree.bind("<FocusIn>",         self._on_focus)
        # 矢印キー: Treeview のデフォルト処理(1行動く)と bind_all(もう1行動く)の
        # 二重発火を防ぐため、ウィジェット自身でバインドして "break" で止める
        for _key, _dir in [("<Up>","up"),("<Down>","down"),
                           ("<Prior>","pgup"),("<Next>","pgdn"),
                           ("<Home>","home"),("<End>","end")]:
            self.tree.bind(_key, lambda e, d=_dir: (self.move_cursor(d), "break")[1])
        # Tab: クラスバインディング(デフォルト遷移)を抑止して確実にパネル切替
        self.tree.bind("<Tab>", lambda e: (self.app._switch_panel_from(self), "break")[1])

    def _setup_style(self):
        s = ttk.Style()
        n = f"TC{self.side}.Treeview"
        s.configure(n,
            background=C["panel_bg"], foreground=C["panel_fg"],
            fieldbackground=C["panel_bg"],
            rowheight=20, font=("Meiryo UI", 9))
        s.map(n,
            background=[("selected", C["cursor_bg"])],
            foreground=[("selected", C["cursor_fg"])])
        s.configure(f"{n}.Heading",
            background=C["hdr_bg"], foreground=C["hdr_fg"],
            font=("Meiryo UI", 9, "bold"), relief="raised")

    def _build_drivebar(self):
        for w in self.drive_frame.winfo_children(): w.destroy()
        drives = get_drives()
        # ドライブコンボ
        self.drive_var = tk.StringVar(value=self.path.drive or drives[0] if drives else "C:")
        cb = ttk.Combobox(self.drive_frame, textvariable=self.drive_var,
            values=drives, width=4, font=("Meiryo UI", 9), state="readonly")
        cb.pack(side="left", padx=2, pady=1)
        cb.bind("<<ComboboxSelected>>", lambda e: self.goto(self.drive_var.get() + "\\"))
        # 空き容量
        free_k, total_k = disk_free(str(self.path.anchor))
        self.space_var = tk.StringVar(value=f"{free_k:,} k / {total_k:,} k free")
        tk.Label(self.drive_frame, textvariable=self.space_var,
            bg=C["bar_bg"], fg=C["bar_fg"], font=("Meiryo UI", 8)
        ).pack(side="left", padx=4)
        # \ .. ボタン
        tk.Button(self.drive_frame, text="\\", width=2,
            bg=C["bar_bg"], font=("Meiryo UI", 8), relief="flat",
            command=self.go_root).pack(side="left")
        tk.Button(self.drive_frame, text="..", width=2,
            bg=C["bar_bg"], font=("Meiryo UI", 8), relief="flat",
            command=self.go_parent).pack(side="left")

    def _build_tabbar(self):
        for w in self.tab_frame.winfo_children(): w.destroy()
        for i, t in enumerate(self.tabs):
            name = Path(t).name or t
            active = (i == self.cur_tab)
            btn = tk.Button(self.tab_frame, text=name, takefocus=False,
                bg=C["active_hdr"] if active else C["bar_bg"],
                fg=C["active_hdr_fg"] if active else C["bar_fg"],
                font=("Meiryo UI", 8), relief="flat", padx=5, pady=0,
                command=lambda idx=i: self._switch_tab(idx))
            btn.pack(side="left")
        tk.Button(self.tab_frame, text="+", bg=C["bar_bg"], fg="#008000",
            font=("Meiryo UI", 8), relief="flat", padx=3, takefocus=False,
            command=self.new_tab).pack(side="left")

    def _switch_tab(self, idx):
        self.tabs[self.cur_tab] = str(self.path)
        self.cur_tab = idx
        self.goto(self.tabs[idx], push_history=False)
        self._build_tabbar()

    def new_tab(self, path=None):
        path = path or str(self.path)
        self.tabs[self.cur_tab] = str(self.path)
        self.tabs.append(str(path))
        self.cur_tab = len(self.tabs) - 1
        self._build_tabbar()
        self.goto(path, push_history=False)

    def close_tab(self):
        if len(self.tabs) <= 1: return
        self.tabs.pop(self.cur_tab)
        self.cur_tab = min(self.cur_tab, len(self.tabs) - 1)
        self._build_tabbar()
        self.goto(self.tabs[self.cur_tab], push_history=False)

    def set_active(self, active):
        """アクティブ/非アクティブの視覚的表示 (ヘッダー色は変えず、カーソル行の青/消灯のみ)"""
        for col, *_ in self.COLS:
            self.tree.heading(col, text=self._header_text(col))
        if active:
            iid = self.tree.focus()
            if iid:
                self.tree.selection_set([iid])
        else:
            self.tree.selection_set([])

    def _header_text(self, col):
        labels = dict((c[0], c[1]) for c in self.COLS)
        txt = labels.get(col, col)
        if col == self.sort_col:
            txt = ("↑" if not self.sort_rev else "↓") + txt
        return txt

    # ── ナビゲーション ──
    def goto(self, path, push_history=True):
        p = Path(path)
        if not p.exists():
            messagebox.showerror("エラー", f"パスが存在しません:\n{path}")
            return
        if not p.is_dir():
            open_file(p); return
        if push_history:
            self.history = self.history[:self.hist_pos + 1]
            self.history.append(str(self.path))
            self.hist_pos = len(self.history) - 1
        self.path = p.resolve()
        self.selected.clear()
        self.q_str = ""
        # ドライブコンボ更新
        drv = str(self.path.drive) if self.path.drive else "/"
        self.drive_var.set(drv)
        free_k, total_k = disk_free(str(self.path.anchor))
        self.space_var.set(f"{free_k:,} k / {total_k:,} k free")
        p = str(self.path)
        sep = "" if p.endswith(("\\", "/")) else "\\"
        self.path_var.set(f"{p}{sep}{self.filter}")
        self.tabs[self.cur_tab] = p
        self._build_tabbar()
        self.refresh()

    def go_parent(self):
        zip_tmp = getattr(self, "_zip_tmp", None)
        if zip_tmp:
            try:
                same = self.path.samefile(zip_tmp)
            except OSError:
                same = False
                self._zip_tmp = None
                self._zip_origin = None
            if same:
                origin = getattr(self, "_zip_origin", None)
                self._zip_tmp = None
                self._zip_origin = None
                self.goto(origin or str(self.path.parent))
                return
        p = self.path.parent
        if p != self.path: self.goto(p)

    def go_root(self):
        self.goto(self.path.anchor)

    def go_back(self):
        if self.hist_pos > 0:
            self.hist_pos -= 1
            self.goto(self.history[self.hist_pos], push_history=False)

    def go_forward(self):
        if self.hist_pos < len(self.history) - 1:
            self.hist_pos += 1
            self.goto(self.history[self.hist_pos], push_history=False)

    def _path_enter(self, _=None):
        val = self.path_var.get().strip()
        # まずそのままディレクトリか確認 (C:\Users\pelpe と直接入力した場合)
        if Path(val).is_dir():
            self.goto(val)
            self.tree.focus_set()
            return
        # 末尾がフィルターパターンの場合 (C:\Users\pelpe\*.py 等)
        if "\\" in val:
            parts = val.rsplit("\\", 1)
            p = parts[0]
            filt = parts[1] if len(parts) > 1 else "*.*"
            if Path(p).is_dir():
                self.filter = filt or "*.*"
                self.goto(p)
                self.tree.focus_set()
                return
        if Path(val).exists():
            self.goto(val)
        self.tree.focus_set()

    def _change_filter(self):
        f = simpledialog.askstring("フィルター", "ファイルフィルター:", initialvalue=self.filter, parent=self)
        if f is not None:
            self.filter = f or "*.*"
            self.refresh()

    # ── 表示更新 ──
    def refresh(self):
        # entries 更新前にカーソル位置を保存
        cur_iid = self.cursor_iid()
        cur_name = None
        cur_idx = 0
        if cur_iid == "__up__":
            cur_name = "__up__"
        elif cur_iid:
            try:
                cur_idx = int(cur_iid)
                cur_name = self.entries[cur_idx]["name"]
            except Exception:
                pass
        raw = list_dir(str(self.path), self.app.cfg.get("show_hidden", True))
        # フィルター適用
        if self.filter not in ("*.*", "*"):
            raw = [e for e in raw if e["is_dir"] or fnmatch.fnmatch(e["name"], self.filter)]
        self.entries = sort_entries(raw, self.sort_col, self.sort_rev)
        self._populate(cur_name, cur_idx)
        self._update_status()
        p = str(self.path)
        sep = "" if p.endswith(("\\", "/")) else "\\"
        self.path_var.set(f"{p}{sep}{self.filter}")

    def _populate(self, cursor_name=None, fallback_idx=0):
        # カーソル名が渡されていない場合は現在のツリーから読む (選択操作等の直接呼び出し用)
        if cursor_name is None:
            cur_iid = self.cursor_iid()
            if cur_iid == "__up__":
                cursor_name = "__up__"
            elif cur_iid:
                try:
                    fallback_idx = int(cur_iid)
                    cursor_name = self.entries[fallback_idx]["name"]
                except Exception:
                    pass
        scroll = self.tree.yview()[0]  # スクロール位置を保存

        self.tree.delete(*self.tree.get_children())
        fi = self.icon_folder; fi2 = self.icon_file
        # 親ディレクトリ
        self.tree.insert("", "end", iid="__up__",
            image=fi, text="",
            values=("[..]", "", "<DIR>", "", ""),
            tags=("dir",))
        for i, e in enumerate(self.entries):
            disp_name = f"[{e['name']}]" if e["is_dir"] else e["name"]
            icon = fi if e["is_dir"] else fi2
            tags = []
            if e["is_dir"]:   tags.append("dir")
            if e["is_link"]:  tags.append("link")
            if i in self.selected: tags.append("sel")
            self.tree.insert("", "end", iid=str(i),
                image=icon, text="",
                values=(disp_name, e["ext"],
                        fmt_size(e["size"]),
                        fmt_date(e["mtime"]),
                        fmt_attr(e["path"])),
                tags=tuple(tags))
        # タグ色
        self.tree.tag_configure("dir",  foreground=C["dir_fg"])
        self.tree.tag_configure("link", foreground=C["link_fg"])
        self.tree.tag_configure("sel",  background=C["sel_bg"], foreground=C["sel_fg"])

        kids = self.tree.get_children()
        if not kids:
            return
        # カーソル位置を復元 (see() は呼ばず、スクロールも維持)
        target_iid = None
        if cursor_name == "__up__":
            target_iid = "__up__"
        elif cursor_name:
            for i, e in enumerate(self.entries):
                if e["name"] == cursor_name:
                    target_iid = str(i)
                    break
        if target_iid is None:
            if cursor_name and cursor_name != "__up__" and self.entries:
                # 削除された場合: 同じインデックス付近に移動
                idx = max(0, min(fallback_idx, len(self.entries) - 1))
                target_iid = str(idx)
            else:
                target_iid = kids[0]  # 初回表示
        self.tree.focus(target_iid)
        self.tree.selection_set([target_iid])
        self.tree.yview_moveto(scroll)

    def _update_status(self):
        total_f = sum(1 for e in self.entries if not e["is_dir"])
        total_s = sum(e["size"] for e in self.entries if not e["is_dir"])
        sel_f   = len(self.selected)
        sel_s   = sum(self.entries[i]["size"] for i in self.selected
                      if i < len(self.entries) and not self.entries[i]["is_dir"])
        if sel_f:
            self.stat_var.set(f"選択 {sel_f} / {fmt_size(sel_s)}    合計 {total_f} / {fmt_size(total_s)}")
        else:
            self.stat_var.set(f"合計 {total_f} ファイル / {fmt_size(total_s)}")

    # ── ヘッダークリック (ソート) ──
    def _click_header(self, col):
        if self.sort_col == col: self.sort_rev = not self.sort_rev
        else: self.sort_col = col; self.sort_rev = False
        for c, *_ in self.COLS:
            self.tree.heading(c, text=self._header_text(c))
        self.refresh()

    # ── カーソル操作 ──
    def _set_cursor(self, iid):
        """カーソル移動: focus + selection_set を同期して可視化する"""
        self.tree.focus(iid)
        self.tree.selection_set([iid])
        self.tree.see(iid)

    def cursor_iid(self):
        return self.tree.focus()

    def cursor_entry(self):
        iid = self.cursor_iid()
        if iid == "__up__": return None
        try: return self.entries[int(iid)]
        except: return None

    def cursor_path(self):
        e = self.cursor_entry()
        return Path(e["path"]) if e else None

    def selected_paths(self):
        if self.selected:
            return [Path(self.entries[i]["path"]) for i in sorted(self.selected) if i < len(self.entries)]
        e = self.cursor_entry()
        return [Path(e["path"])] if e else []

    def move_cursor(self, direction):
        kids = list(self.tree.get_children())
        if not kids: return
        cur = self.cursor_iid()
        idx = kids.index(cur) if cur in kids else 0
        n = {"up": max(0, idx-1), "down": min(len(kids)-1, idx+1),
             "pgup": max(0, idx-15), "pgdn": min(len(kids)-1, idx+15),
             "home": 0, "end": len(kids)-1}.get(direction, idx)
        self._set_cursor(kids[n])

    def enter_cursor(self):
        iid = self.cursor_iid()
        if iid == "__up__": self.go_parent(); return
        try: idx = int(iid)
        except: return
        if idx >= len(self.entries): return
        e = self.entries[idx]
        if e["is_dir"]: self.goto(e["path"])
        elif Path(e["path"]).suffix.lower() == ".zip" and zipfile.is_zipfile(e["path"]): self._browse_zip(e["path"])
        else: open_file(Path(e["path"]))

    def _browse_zip(self, zip_path):
        """ZIPファイルをブラウズ (簡易実装 - 展開先を一時表示)"""
        if Path(zip_path).suffix.lower() != ".zip":
            open_file(Path(zip_path))
            return
        import tempfile
        tmp = tempfile.mkdtemp(prefix="launcher_zip_")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            self._zip_tmp    = str(Path(tmp).resolve())
            self._zip_origin = str(Path(zip_path).parent)
            self.goto(tmp)
        except Exception as ex:
            messagebox.showerror("エラー", f"ZIP展開エラー: {ex}")

    # ── 選択操作 ──
    def toggle_select(self, iid=None):
        if iid is None: iid = self.cursor_iid()
        if iid == "__up__": return
        try: idx = int(iid)
        except: return
        if idx in self.selected: self.selected.discard(idx)
        else: self.selected.add(idx)
        self._repaint(iid, idx)
        self._update_status()
        # 次行へ移動
        kids = list(self.tree.get_children())
        pos = kids.index(iid) if iid in kids else 0
        if pos + 1 < len(kids):
            self._set_cursor(kids[pos + 1])

    def _repaint(self, iid, idx):
        e = self.entries[idx]
        tags = (["dir"] if e["is_dir"] else []) + \
               (["link"] if e["is_link"] else []) + \
               (["sel"] if idx in self.selected else [])
        self.tree.item(iid, tags=tuple(tags))

    def select_all(self):
        for i in range(len(self.entries)): self.selected.add(i)
        self._populate(); self._update_status()

    def deselect_all(self):
        self.selected.clear()
        self._populate(); self._update_status()

    def invert_sel(self):
        self.selected = set(range(len(self.entries))) - self.selected
        self._populate(); self._update_status()

    def select_by_pattern(self, add=True):
        pat = simpledialog.askstring(
            "選択" if add else "選択解除",
            "パターン (例: *.py, *.txt):", parent=self)
        if not pat: return
        for i, e in enumerate(self.entries):
            if fnmatch.fnmatch(e["name"], pat):
                if add: self.selected.add(i)
                else: self.selected.discard(i)
        self._populate(); self._update_status()

    def select_same_ext(self, add=True):
        e = self.cursor_entry()
        if not e: return
        ext = e["ext"]
        for i, en in enumerate(self.entries):
            if en["ext"] == ext:
                if add: self.selected.add(i)
                else: self.selected.discard(i)
        self._populate(); self._update_status()

    def save_selection(self):
        self.saved_sel = [self.entries[i]["name"] for i in self.selected if i < len(self.entries)]

    def restore_selection(self):
        names = set(self.saved_sel)
        self.selected = {i for i, e in enumerate(self.entries) if e["name"] in names}
        self._populate(); self._update_status()

    # ── イベントハンドラ ──
    def _click(self, event):
        self.app.set_active(self.side)
        iid = self.tree.identify_row(event.y)
        if iid: self._set_cursor(iid)

    def _dbl_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid: return
        if iid == "__up__": self.go_parent(); return
        try: idx = int(iid); e = self.entries[idx]
        except: return
        if e["is_dir"]: self.goto(e["path"])
        else: open_file(Path(e["path"]))

    def _right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid: self._set_cursor(iid)
        self.app.show_ctx_menu(event)

    def _on_focus(self, _):
        self.app.set_active(self.side)

    # ── クイック検索 ──
    def quick_search(self, ch):
        self.q_str += ch.lower()
        if self.q_timer: self.after_cancel(self.q_timer)
        self.q_timer = self.after(1500, self._clear_qs)
        self.app.set_status(f"検索: {self.q_str}")
        for iid in self.tree.get_children():
            if iid == "__up__": continue
            try:
                nm = self.entries[int(iid)]["name"].lower()
                if nm.startswith(self.q_str):
                    self._set_cursor(iid); return
            except: pass
        self.q_str = ch.lower()

    def _clear_qs(self):
        self.q_str = ""
        self.app.set_status("")

    # ── 表示モード ──
    def set_brief(self, brief):
        self.brief_mode = brief
        if brief:
            for col, *_ in self.COLS[1:]: self.tree.column(col, width=0, minwidth=0)
            self.tree.column("name", width=200)
        else:
            for col, label, width, anchor in self.COLS:
                self.tree.column(col, width=width, minwidth=30)


# ── ダイアログ類 ────────────────────────────────────
class VenvSelectDialog(tk.Toplevel):
    """ベースパス群から仮想環境を列挙して選択するダイアログ"""
    def __init__(self, master, venv_bases):
        super().__init__(master)
        self.title("仮想環境を選択")
        self.resizable(False, False)
        self.result = None  # 選択された activate.bat の Path、またはFalse(venvなし起動)
        self.grab_set()

        # ベースパス群から activate.bat を持つ仮想環境を収集
        self._entries = []  # (表示名, activate_path)
        for base in venv_bases:
            bp = Path(base)
            if not bp.is_dir():
                continue
            for sub in sorted(bp.iterdir()):
                act = sub / "Scripts" / "activate.bat"
                if sub.is_dir() and act.exists():
                    self._entries.append((f"{sub.name}  [{bp.name}]", act))

        tk.Label(self, text="activate する仮想環境:", font=("Meiryo UI", 9)).pack(padx=12, pady=(10,2), anchor="w")

        fr = tk.Frame(self); fr.pack(padx=12, pady=4)
        sb = tk.Scrollbar(fr); sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(fr, yscrollcommand=sb.set, font=("Meiryo UI", 9),
                             width=52, height=12, selectmode="single",
                             exportselection=False,
                             selectbackground="#000080", selectforeground="#FFFFFF")
        self.lb.pack(side="left")
        sb.config(command=self.lb.yview)
        for label, _ in self._entries:
            self.lb.insert("end", label)
        if self._entries:
            self.lb.selection_set(0)
            self.lb.activate(0)

        btn_fr = tk.Frame(self); btn_fr.pack(pady=8)
        tk.Button(btn_fr, text="OK",              width=10, command=self._ok).pack(side="left", padx=4)
        tk.Button(btn_fr, text="venvなしで開く",  width=14, command=self._no_venv).pack(side="left", padx=4)
        tk.Button(btn_fr, text="キャンセル",      width=10, command=self.destroy).pack(side="left", padx=4)

        # 矢印キー等でアクティブ項目が変わったら selection を追従させる
        def _sync_sel(event=None):
            self.lb.after(0, lambda: (
                self.lb.selection_clear(0, "end"),
                self.lb.selection_set(self.lb.index("active")),
            ))
        for key in ("<Up>", "<Down>", "<Prior>", "<Next>", "<Home>", "<End>"):
            self.lb.bind(key, _sync_sel)

        self.lb.bind("<Double-Button-1>", lambda e: self._ok())
        self.bind("<Return>", lambda e: self._ok() or "break")
        self.bind("<Escape>", lambda _: self.destroy())
        # after で遅延させてウィンドウ表示後に確実にフォーカスを当てる
        self.after(50, lambda: self.lb.focus_set())
        self.wait_window()

    def _ok(self):
        sel = self.lb.curselection()
        if not sel:
            return
        self.result = self._entries[sel[0]][1]  # activate.bat の Path
        self.destroy()

    def _no_venv(self):
        self.result = False  # venv なしで開くフラグ
        self.destroy()


class VenvBasesDialog(tk.Toplevel):
    """venv 集合フォルダ（ベースパス）を複数管理するダイアログ"""
    def __init__(self, master, bases):
        super().__init__(master)
        self.title("venv ベースパス設定")
        self.resizable(False, False)
        self.result = None
        self.grab_set()

        tk.Label(self, text="仮想環境を格納しているフォルダ一覧:", font=("Meiryo UI", 9)).pack(padx=12, pady=(10,2), anchor="w")

        frame = tk.Frame(self); frame.pack(padx=12, pady=4, fill="both")
        sb = tk.Scrollbar(frame); sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(frame, yscrollcommand=sb.set, font=("Meiryo UI", 9),
                             width=55, height=8, selectmode="single")
        self.lb.pack(side="left", fill="both")
        sb.config(command=self.lb.yview)
        for b in bases:
            self.lb.insert("end", b)

        btn_fr = tk.Frame(self); btn_fr.pack(padx=12, pady=4, fill="x")
        tk.Button(btn_fr, text="追加",   width=8, command=self._add).pack(side="left", padx=2)
        tk.Button(btn_fr, text="削除",   width=8, command=self._del).pack(side="left", padx=2)
        tk.Button(btn_fr, text="↑",     width=4, command=lambda: self._move(-1)).pack(side="left", padx=2)
        tk.Button(btn_fr, text="↓",     width=4, command=lambda: self._move(1)).pack(side="left", padx=2)

        ok_fr = tk.Frame(self); ok_fr.pack(pady=8)
        tk.Button(ok_fr, text="OK",       width=10, command=self._ok).pack(side="left", padx=5)
        tk.Button(ok_fr, text="キャンセル", width=10, command=self.destroy).pack(side="left", padx=5)
        self.bind("<Return>", lambda e: self._ok() or "break")
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_window()

    def _add(self):
        path = simpledialog.askstring("パスを追加",
            "仮想環境を格納しているフォルダのパス:", parent=self)
        if path and path.strip():
            self.lb.insert("end", path.strip())

    def _del(self):
        sel = self.lb.curselection()
        if sel: self.lb.delete(sel[0])

    def _move(self, delta):
        sel = self.lb.curselection()
        if not sel: return
        idx = sel[0]
        new = idx + delta
        if new < 0 or new >= self.lb.size(): return
        val = self.lb.get(idx)
        self.lb.delete(idx)
        self.lb.insert(new, val)
        self.lb.selection_set(new)

    def _ok(self):
        self.result = list(self.lb.get(0, "end"))
        self.destroy()


class _BaseDialog(tk.Toplevel):
    def __init__(self, master, title):
        super().__init__(master)
        self.title(title); self.resizable(False, False)
        self.result = None
        self.grab_set(); self.focus_set()
        self.bind("<Escape>", lambda _: self.destroy())

class CopyMoveDialog(_BaseDialog):
    def __init__(self, master, sources, dest, move=False):
        super().__init__(master, "移動" if move else "コピー")
        verb = "移動" if move else "コピー"
        n = len(sources)
        lbl = sources[0].name if n == 1 else f"{n} 個のファイル/フォルダ"
        tk.Label(self, text=f"{lbl} を{verb}先:").pack(padx=12, pady=(10,2), anchor="w")
        self.var = tk.StringVar(value=str(dest))
        e = tk.Entry(self, textvariable=self.var, width=56, font=("Meiryo UI", 9))
        e.pack(padx=12, pady=2, fill="x"); e.selection_range(0, "end"); e.focus_set()
        fr = tk.Frame(self); fr.pack(pady=8)
        tk.Button(fr, text=f"{'F6' if move else 'F5'} {verb}", width=12,
            command=self._ok).pack(side="left", padx=5)
        tk.Button(fr, text="キャンセル", width=10,
            command=self.destroy).pack(side="left", padx=5)
        self.bind("<Return>", lambda e: self._ok() or "break")
        self.wait_window()
    def _ok(self): self.result = self.var.get(); self.destroy()

class RenameDialog(_BaseDialog):
    def __init__(self, master, name):
        super().__init__(master, "リネーム")
        tk.Label(self, text="新しい名前:").pack(padx=12, pady=(10,2), anchor="w")
        self.var = tk.StringVar(value=name)
        e = tk.Entry(self, textvariable=self.var, width=48, font=("Meiryo UI", 9))
        e.pack(padx=12, pady=2, fill="x")
        dot = name.rfind(".")
        e.focus_set()
        e.after(10, lambda: e.selection_range(0, dot if dot > 0 else "end"))
        fr = tk.Frame(self); fr.pack(pady=8)
        tk.Button(fr, text="OK", width=10, command=self._ok).pack(side="left", padx=5)
        tk.Button(fr, text="キャンセル", width=10, command=self.destroy).pack(side="left", padx=5)
        self.bind("<Return>", lambda e: self._ok() or "break")
        self.wait_window()
    def _ok(self): self.result = self.var.get(); self.destroy()

class MkdirDialog(_BaseDialog):
    def __init__(self, master):
        super().__init__(master, "新規ディレクトリ作成 (F7)")
        tk.Label(self, text="ディレクトリ名:").pack(padx=12, pady=(10,2), anchor="w")
        self.var = tk.StringVar()
        e = tk.Entry(self, textvariable=self.var, width=48, font=("Meiryo UI", 9))
        e.pack(padx=12, pady=2, fill="x"); e.focus_set()
        fr = tk.Frame(self); fr.pack(pady=8)
        tk.Button(fr, text="OK", width=10, command=self._ok).pack(side="left", padx=5)
        tk.Button(fr, text="キャンセル", width=10, command=self.destroy).pack(side="left", padx=5)
        self.bind("<Return>", lambda e: self._ok() or "break")
        self.wait_window()
    def _ok(self): self.result = self.var.get(); self.destroy()

class FindDialog(tk.Toplevel):
    def __init__(self, master, start_path):
        super().__init__(master)
        self.title("ファイル検索 (Alt+F7)")
        self.geometry("600x480")
        self.start_path = start_path
        self.results = []
        self._build(); self.grab_set()

    def _build(self):
        fr = tk.LabelFrame(self, text="検索条件", padx=6, pady=6)
        fr.pack(fill="x", padx=8, pady=6)
        def row(parent, r, label, var, width=40):
            tk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=2)
            e = tk.Entry(parent, textvariable=var, width=width, font=("Meiryo UI", 9))
            e.grid(row=r, column=1, sticky="ew", padx=4, pady=2)
            return e
        self.name_v = tk.StringVar(value="*")
        self.path_v = tk.StringVar(value=str(self.start_path))
        self.text_v = tk.StringVar()
        self.sub_v  = tk.BooleanVar(value=True)
        row(fr, 0, "ファイル名:", self.name_v)
        row(fr, 1, "検索フォルダ:", self.path_v)
        row(fr, 2, "テキスト検索:", self.text_v).focus_set()
        tk.Checkbutton(fr, text="サブディレクトリも検索", variable=self.sub_v).grid(
            row=3, column=1, sticky="w")
        fr.columnconfigure(1, weight=1)
        bf = tk.Frame(self); bf.pack(fill="x", padx=8)
        tk.Button(bf, text="検索開始 (Enter)", command=self._search).pack(side="left", padx=4)
        tk.Button(bf, text="閉じる", command=self.destroy).pack(side="left")
        self.listbox = tk.Listbox(self, font=("Meiryo UI", 9), height=14,
            selectbackground=C["sel_bg"], selectforeground=C["sel_fg"])
        sb = tk.Scrollbar(self, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0,8), pady=4)
        self.listbox.pack(fill="both", expand=True, padx=8, pady=4)
        self.listbox.bind("<Double-Button-1>", self._open)
        self.listbox.bind("<Return>", self._open)
        self.stat_v = tk.StringVar(value="条件を入力して「検索開始」を押してください")
        tk.Label(self, textvariable=self.stat_v, anchor="w",
            font=("Meiryo UI", 8)).pack(fill="x", padx=8, pady=2)
        self.bind("<Return>", lambda _: self._search())

    def _search(self):
        self.listbox.delete(0, "end"); self.results = []
        pat  = self.name_v.get() or "*"
        root = Path(self.path_v.get())
        text = self.text_v.get()
        if not root.exists(): messagebox.showerror("エラー", "フォルダが存在しません"); return
        self.stat_v.set("検索中..."); self.update_idletasks()
        count = 0
        try:
            walker = root.rglob("*") if self.sub_v.get() else root.iterdir()
            for p in walker:
                if fnmatch.fnmatch(p.name, pat):
                    if text:
                        try:
                            if text.lower() in p.read_text(errors="ignore").lower():
                                self.results.append(p)
                                self.listbox.insert("end", str(p)); count += 1
                        except: pass
                    else:
                        self.results.append(p)
                        self.listbox.insert("end", str(p)); count += 1
                if count % 100 == 0: self.update_idletasks()
        except Exception as ex:
            messagebox.showerror("エラー", str(ex))
        self.stat_v.set(f"{count} 件見つかりました")

    def _open(self, _=None):
        sel = self.listbox.curselection()
        if sel:
            p = self.results[sel[0]]
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(p)])

class MultiRenameDialog(tk.Toplevel):
    def __init__(self, master, files):
        super().__init__(master); self.title("一括リネーム (Ctrl+M)")
        self.files = files; self.geometry("700x500"); self._build(); self.grab_set()

    def _build(self):
        top = tk.LabelFrame(self, text="リネーム設定", padx=6, pady=4)
        top.pack(fill="x", padx=8, pady=6)
        def row(parent, r, label, var):
            tk.Label(parent, text=label).grid(row=r, column=0, sticky="w")
            e = tk.Entry(parent, textvariable=var, width=42, font=("Meiryo UI", 9))
            e.grid(row=r, column=1, sticky="ew", padx=4, pady=2)
        self.sv = tk.StringVar(); self.rv = tk.StringVar()
        self.nv = tk.StringVar(value="1"); self.rgx = tk.BooleanVar()
        row(top, 0, "検索文字列:", self.sv)
        row(top, 1, "置換文字列:", self.rv)
        row(top, 2, "開始番号 [N]:", self.nv)
        tk.Checkbutton(top, text="正規表現", variable=self.rgx).grid(
            row=3, column=1, sticky="w")
        top.columnconfigure(1, weight=1)
        bf = tk.Frame(self); bf.pack(fill="x", padx=8)
        tk.Button(bf, text="プレビュー", command=self._preview).pack(side="left", padx=4)
        tk.Button(bf, text="実行",       command=self._run).pack(side="left", padx=4)
        tk.Button(bf, text="閉じる",     command=self.destroy).pack(side="left")
        cols = ("before","after")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=15)
        self.tv.heading("before", text="変更前"); self.tv.column("before", width=300)
        self.tv.heading("after",  text="変更後"); self.tv.column("after",  width=300)
        self.tv.pack(fill="both", expand=True, padx=8, pady=6)
        self._preview()

    def _new_name(self, name, idx):
        s = self.sv.get(); r = self.rv.get()
        try: start = int(self.nv.get())
        except: start = 1
        r2 = r.replace("[N]", str(start + idx))
        if not s: return name
        try:
            if self.rgx.get(): return re.sub(s, r2, name)
            return name.replace(s, r2)
        except: return name

    def _preview(self):
        self.tv.delete(*self.tv.get_children())
        for i, f in enumerate(self.files):
            self.tv.insert("", "end", values=(f.name, self._new_name(f.name, i)))

    def _run(self):
        errs = []
        for i, f in enumerate(self.files):
            nn = self._new_name(f.name, i)
            if nn != f.name:
                try: f.rename(f.parent / nn)
                except Exception as ex: errs.append(f"{f.name}: {ex}")
        if errs: messagebox.showerror("エラー", "\n".join(errs[:10]))
        else: messagebox.showinfo("完了", f"{len(self.files)}件完了")
        self.destroy()

class HotlistMenu(tk.Toplevel):
    """TC スタイルのホットリストポップアップ (overrideredirect)"""

    def __init__(self, master, hotlist, cur_path, target_path, on_goto, on_save):
        super().__init__(master)
        self.overrideredirect(True)
        self.hotlist  = hotlist
        self.cur_path = Path(cur_path)
        self.tgt_path = Path(target_path)
        self.on_goto  = on_goto   # callable(path_str, target_str_or_None)
        self.on_save  = on_save   # callable()
        self._rows    = []        # list of (widget, key)  key=None → separator
        self._sel     = 0
        self._build()
        self._position(master)
        self.grab_set()
        self.bind("<Up>",     lambda e: self._move(-1) or "break")
        self.bind("<Down>",   lambda e: self._move(1)  or "break")
        self.bind("<Return>", lambda e: self._activate() or "break")
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()

    # ── UI 構築 ──────────────────────────────
    def _build(self):
        self.configure(bg=C["hdr_bg"], bd=1, relief="solid")
        outer = tk.Frame(self, bg=C["panel_bg"]); outer.pack(fill="both", expand=True)

        def item(text, key):
            lbl = tk.Label(outer, text=f"  {text}  ", bg=C["panel_bg"], fg=C["panel_fg"],
                           font=("Meiryo UI", 9), anchor="w", padx=2, pady=2)
            lbl.pack(fill="x")
            i = len(self._rows)
            lbl.bind("<Button-1>", lambda e, i=i: self._click(i))
            lbl.bind("<Enter>",    lambda e, i=i: self._hover(i))
            self._rows.append((lbl, key))

        def sep():
            f = tk.Frame(outer, height=1, bg=C["hdr_bg"]); f.pack(fill="x", pady=1)
            self._rows.append((f, None))

        item("Add current dir", "ADD")
        item("Configure...",    "CFG")
        if self.hotlist:
            sep()
            for name in self.hotlist:
                item(name, name)

        self._highlight()

    def _highlight(self):
        for i, (w, key) in enumerate(self._rows):
            if key is None: continue
            w.config(bg=C["cursor_bg"] if i == self._sel else C["panel_bg"],
                     fg=C["cursor_fg"] if i == self._sel else C["panel_fg"])

    def _selectable(self):
        return [i for i, (_, k) in enumerate(self._rows) if k is not None]

    def _select(self, idx):
        self._sel = idx; self._highlight()

    def _hover(self, idx):
        self._select(idx)

    def _move(self, d):
        idxs = self._selectable()
        if not idxs: return
        try: pos = idxs.index(self._sel)
        except ValueError: pos = 0
        self._select(idxs[(pos + d) % len(idxs)])

    def _click(self, idx):
        self._select(idx); self._activate()

    def _activate(self):
        if self._sel >= len(self._rows): return
        _, key = self._rows[self._sel]
        if key is None: return
        if   key == "ADD": self._do_add()
        elif key == "CFG": self._do_configure()
        else:
            val = self.hotlist.get(key)
            if val is None: self.destroy(); return
            path   = val.get("path", "")   if isinstance(val, dict) else str(val)
            target = val.get("target", "") if isinstance(val, dict) else None
            self.on_goto(path, target or None)
            self.destroy()

    # ── サブダイアログ ────────────────────────
    def _do_add(self):
        self.grab_release()
        dlg = HotlistAddDialog(self.master, self.cur_path, self.tgt_path)
        if dlg.result:
            name, path, target = dlg.result
            self.hotlist[name] = ({"path": str(path), "target": str(target)}
                                  if target else str(path))
            self.on_save()
        self.destroy()

    def _do_configure(self):
        self.grab_release()
        HotlistConfigDialog(self.master, self.hotlist, self.on_save)
        self.destroy()

    # ── 位置決め ──────────────────────────────
    def _position(self, master):
        self.update_idletasks()
        try:
            tree = master.ap.tree
            x, y = tree.winfo_rootx(), tree.winfo_rooty()
        except Exception:
            x, y = master.winfo_rootx() + 10, master.winfo_rooty() + 60
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{min(x, sw-w-4)}+{min(y, sh-h-4)}")


class HotlistAddDialog(_BaseDialog):
    """Add current dir — 名前入力 + Also save the target dir チェック"""
    def __init__(self, master, cur_path, target_path):
        super().__init__(master, "New title for menu entry")
        self.cur_path = cur_path; self.target_path = target_path

        self.name_var = tk.StringVar(value=cur_path.name)
        e = tk.Entry(self, textvariable=self.name_var, width=36, font=("Meiryo UI", 9))
        e.pack(padx=12, pady=(10, 4), fill="x")
        e.after(10, lambda: (e.focus_set(), e.selection_range(0, "end")))

        self.also_tgt = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Also save the target dir",
                       variable=self.also_tgt, font=("Meiryo UI", 9)
                       ).pack(padx=12, pady=4, anchor="w")

        fr = tk.Frame(self); fr.pack(pady=8)
        tk.Button(fr, text="OK",     width=10, command=self._ok).pack(side="left", padx=4)
        tk.Button(fr, text="Cancel", width=10, command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda e: self._ok() or "break")
        self.wait_window()

    def _ok(self):
        name = self.name_var.get().strip()
        if not name: return
        self.result = (name, self.cur_path,
                       self.target_path if self.also_tgt.get() else None)
        self.destroy()


class HotlistConfigDialog(tk.Toplevel):
    """Configure... — ホットリスト管理ダイアログ"""
    def __init__(self, master, hotlist, on_save):
        super().__init__(master)
        self.title("ホットリスト設定 (Configure)")
        self.hotlist = hotlist; self.on_save = on_save
        self.grab_set()
        self._build()
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_window()

    def _build(self):
        fr = tk.Frame(self); fr.pack(fill="both", expand=True, padx=8, pady=8)
        sb = tk.Scrollbar(fr); sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(fr, yscrollcommand=sb.set, font=("Meiryo UI", 9),
                             width=58, height=14, selectmode="single",
                             exportselection=False,
                             selectbackground=C["cursor_bg"],
                             selectforeground=C["cursor_fg"])
        self.lb.pack(side="left", fill="both", expand=True)
        sb.config(command=self.lb.yview)
        self._reload()

        def _sync(e=None):
            self.lb.after(0, lambda: (self.lb.selection_clear(0, "end"),
                                      self.lb.selection_set(self.lb.index("active"))))
        for k in ("<Prior>", "<Next>", "<Home>", "<End>"):
            self.lb.bind(k, _sync)
        # ↑↓ は移動操作に使うため通常の _sync は付けない
        self.lb.bind("<Up>",   lambda e: self._move_sel(-1) or "break")
        self.lb.bind("<Down>", lambda e: self._move_sel(1)  or "break")
        # Alt+↑↓ で並び替え
        self.lb.bind("<Alt-Up>",   lambda e: self._move_item(-1) or "break")
        self.lb.bind("<Alt-Down>", lambda e: self._move_item(1)  or "break")

        bf = tk.Frame(self); bf.pack(pady=4)
        tk.Button(bf, text="↑",      width=4,  command=lambda: self._move_item(-1)).pack(side="left", padx=2)
        tk.Button(bf, text="↓",      width=4,  command=lambda: self._move_item(1)).pack(side="left", padx=2)
        tk.Button(bf, text="削除",   width=10, command=self._del).pack(side="left", padx=4)
        tk.Button(bf, text="閉じる", width=10, command=self.destroy).pack(side="left", padx=4)
        self.lb.focus_set()
        if self.lb.size():
            self.lb.selection_set(0); self.lb.activate(0)

    def _reload(self):
        self.lb.delete(0, "end")
        for name, val in self.hotlist.items():
            path   = val.get("path", "")   if isinstance(val, dict) else str(val)
            target = val.get("target", "") if isinstance(val, dict) else ""
            suffix = f"  [target: {target}]" if target else ""
            self.lb.insert("end", f"{name}  →  {path}{suffix}")

    def _del(self):
        sel = self.lb.curselection()
        if not sel: return
        key = list(self.hotlist.keys())[sel[0]]
        del self.hotlist[key]; self.on_save(); self._reload()
        new = min(sel[0], self.lb.size() - 1)
        if new >= 0: self.lb.selection_set(new); self.lb.activate(new)

    def _move_sel(self, d):
        """↑↓ キーでカーソル移動 (selection を同期)"""
        sel = self.lb.curselection()
        cur = sel[0] if sel else self.lb.index("active")
        new = max(0, min(cur + d, self.lb.size() - 1))
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(new)
        self.lb.activate(new)
        self.lb.see(new)

    def _move_item(self, d):
        """↑↓ ボタン / Alt+↑↓ でエントリの順番を入れ替える"""
        sel = self.lb.curselection()
        if not sel: return
        idx = sel[0]
        items = list(self.hotlist.items())
        new_idx = idx + d
        if new_idx < 0 or new_idx >= len(items): return
        items[idx], items[new_idx] = items[new_idx], items[idx]
        self.hotlist.clear()
        for k, v in items:
            self.hotlist[k] = v
        self.on_save()
        self._reload()
        self.lb.selection_set(new_idx)
        self.lb.activate(new_idx)
        self.lb.see(new_idx)

# ── メインウィンドウ ─────────────────────────────────
class App(tk.Tk):
    def __init__(self, left_path=None, right_path=None):
        super().__init__()
        # Windows デフォルトテーマは ttk heading の foreground を無視して暗色描画するため
        # "clam" テーマに切り替えてカスタムカラーを確実に反映させる
        ttk.Style().theme_use("clam")
        self.cfg = load_cfg()
        self.title(APP_NAME)
        self.geometry(self.cfg.get("geometry", "1280x720"))
        # ウィンドウアイコン設定 (PNG を PhotoImage で読み込む)
        _icon_path = _SCRIPT_DIR / "ロケットアイコン.png"
        if _icon_path.exists():
            try:
                self._app_icon = tk.PhotoImage(file=str(_icon_path))
                self.iconphoto(True, self._app_icon)
            except Exception:
                pass
        self._active_side = "left"
        self._build_menu()
        self._build_toolbar()
        # fnbar/cmdlineは side="bottom" で先にpackしてからpanelsをexpand=Trueでpack
        self._build_fnbar()
        self._build_cmdline()
        self._build_panels(
            left_path  or self.cfg["left_path"],
            right_path or self.cfg["right_path"])
        self._build_mid_buttons()
        self._bind_keys()
        self._disable_tab_focus()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, lambda: self.left.tree.focus_set())

    # ── UI構築 ──
    def _build_menu(self):
        mb = tk.Menu(self)
        def add(menu, label):
            m = tk.Menu(mb, tearoff=0); mb.add_cascade(label=label, menu=m); return m
        # Files
        f = add(mb, "ファイル(F)")
        f.add_command(label="表示           F3",          command=self.cmd_view)
        f.add_command(label="編集           F4",          command=self.cmd_edit)
        f.add_command(label="VSCodeで開く   Ctrl+Enter",  command=self.cmd_vscode)
        f.add_command(label="コピー         F5",          command=self.cmd_copy)
        f.add_command(label="移動/リネーム  F6",          command=self.cmd_move)
        f.add_command(label="新規ディレクトリ  F7",       command=self.cmd_mkdir)
        f.add_command(label="削除           F8",          command=self.cmd_delete)
        f.add_separator()
        f.add_command(label="属性変更",                   command=self.cmd_set_attr)
        f.add_command(label="プロパティ  Alt+Enter",      command=self.cmd_properties)
        f.add_separator()
        f.add_command(label="終了  Alt+F4",               command=self._close)
        # Mark
        m = add(mb, "選択(M)")
        m.add_command(label="グループ選択   Num+",        command=lambda: self.ap.select_by_pattern(True))
        m.add_command(label="グループ解除   Num-",        command=lambda: self.ap.select_by_pattern(False))
        m.add_command(label="全選択         Ctrl+A",      command=lambda: self.ap.select_all())
        m.add_command(label="全解除",                     command=lambda: self.ap.deselect_all())
        m.add_command(label="選択反転       Num*",        command=lambda: self.ap.invert_sel())
        m.add_command(label="同拡張子を選択 Alt+Num+",    command=lambda: self.ap.select_same_ext(True))
        m.add_command(label="同拡張子を解除 Alt+Num-",    command=lambda: self.ap.select_same_ext(False))
        m.add_separator()
        m.add_command(label="選択を保存     Num/",        command=lambda: self.ap.save_selection())
        m.add_command(label="選択を復元     Num/",        command=lambda: self.ap.restore_selection())
        m.add_separator()
        m.add_command(label="ファイル名をコピー",         command=self.cmd_copy_names)
        m.add_command(label="フルパスをコピー",           command=self.cmd_copy_full_names)
        m.add_separator()
        m.add_command(label="ディレクトリ比較  Shift+F2", command=self.cmd_compare_dirs)
        # Commands
        c = add(mb, "コマンド(C)")
        c.add_command(label="検索           Alt+F7",      command=self.cmd_find)
        c.add_command(label="一括リネーム   Ctrl+M",      command=self.cmd_multi_rename)
        c.add_command(label="ディレクトリホットリスト  Ctrl+D", command=self.cmd_hotlist)
        c.add_separator()
        c.add_command(label="コマンドプロンプト",         command=self.cmd_terminal)
        c.add_command(label="コマンドプロンプト (PowerShell)", command=self.cmd_terminal_ps)
        c.add_separator()
        c.add_command(label="ソース<->ターゲット  Ctrl+U", command=self.cmd_exchange)
        c.add_command(label="ターゲット=ソース  Ctrl+I",   command=self.cmd_match_src)
        # Show
        v = add(mb, "表示(V)")
        v.add_command(label="簡易表示       Ctrl+F1",     command=lambda: self.cmd_view_mode(True))
        v.add_command(label="詳細表示       Ctrl+F2",     command=lambda: self.cmd_view_mode(False))
        v.add_separator()
        v.add_command(label="名前順         Ctrl+F3",     command=lambda: self.cmd_sort("name"))
        v.add_command(label="拡張子順       Ctrl+F4",     command=lambda: self.cmd_sort("ext"))
        v.add_command(label="更新日時順     Ctrl+F5",     command=lambda: self.cmd_sort("date"))
        v.add_command(label="サイズ順       Ctrl+F6",     command=lambda: self.cmd_sort("size"))
        v.add_separator()
        v.add_command(label="隠しファイル表示切替", command=self.cmd_toggle_hidden)
        v.add_command(label="クイックフィルター  Ctrl+S",  command=self.cmd_quick_filter)
        v.add_separator()
        v.add_command(label="再読み込み     Ctrl+R",      command=lambda: self.ap.refresh())
        # Config
        cfg = add(mb, "設定(O)")
        cfg.add_command(label="設定ファイルの場所を変更",   command=self.cmd_cfg_location)
        cfg.add_separator()
        cfg.add_command(label="エディタ設定",             command=self.cmd_cfg_editor)
        cfg.add_command(label="venvベースパス設定",        command=self.cmd_cfg_venv)
        cfg.add_command(label="コマンドラインの表示切替", command=self.cmd_toggle_cmdline)
        cfg.add_command(label="ファンクションキーバーの表示切替", command=self.cmd_toggle_fnbar)
        cfg.add_separator()
        cfg.add_command(label="設定を保存",               command=lambda: save_cfg(self.cfg))
        # Help
        h = add(mb, "ヘルプ(H)")
        h.add_command(label="キーボードショートカット  F1", command=self.cmd_help)
        self.config(menu=mb)

    def _build_toolbar(self):
        self.toolbar = tk.Frame(self, bg=C["bar_bg"], relief="raised", bd=1)
        self.toolbar.pack(fill="x")
        def tb(text, cmd, tip=""):
            b = tk.Button(self.toolbar, text=text, command=cmd,
                bg=C["bar_bg"], font=("Meiryo UI", 7),
                relief="flat", padx=4, pady=1)
            b.pack(side="left", padx=1)
            return b
        tb("↺ 更新", lambda: self.ap.refresh())
        tk.Frame(self.toolbar, width=2, bg="#808080").pack(side="left", fill="y", padx=2)
        tb("← 戻る",   self.cmd_back)
        tb("→ 進む",   self.cmd_forward)
        tk.Frame(self.toolbar, width=2, bg="#808080").pack(side="left", fill="y", padx=2)
        tb("F3 表示",  self.cmd_view)
        tb("F4 編集",  self.cmd_edit)
        tb("F5 コピー", self.cmd_copy)
        tb("F6 移動",  self.cmd_move)
        tb("F7 新規Dir", self.cmd_mkdir)
        tb("F8 削除",  self.cmd_delete)
        tk.Frame(self.toolbar, width=2, bg="#808080").pack(side="left", fill="y", padx=2)
        tb("検索", self.cmd_find)
        tb("リネーム", self.cmd_multi_rename)
        tb("Ctrl+U 交換", self.cmd_exchange)

    def _build_panels(self, left_path, right_path):
        self.panel_container = tk.Frame(self, bg=C["bar_bg"])
        self.panel_container.pack(fill="both", expand=True)

        self.left  = FilePanel(self.panel_container, self, "left",  left_path)
        self.right = FilePanel(self.panel_container, self, "right", right_path)

        self.left.grid (row=0, column=0, sticky="nsew", padx=(0,1))
        self.right.grid(row=0, column=2, sticky="nsew", padx=(1,0))
        self.panel_container.columnconfigure(0, weight=1)
        self.panel_container.columnconfigure(2, weight=1)
        self.panel_container.rowconfigure(0, weight=1)
        self.set_active("left")

    def _build_mid_buttons(self):
        """パネル間の縦型ボタンバー (TCのvertical.barに相当)"""
        mid = tk.Frame(self.panel_container, bg=C["mid_bg"], width=28)
        mid.grid(row=0, column=1, sticky="ns")
        mid.pack_propagate(False)
        btns = [
            ("👁", self.cmd_view,   "表示 F3"),
            ("✎", self.cmd_edit,   "編集 F4"),
            ("⎘", self.cmd_copy,   "コピー F5"),
            ("⇒", self.cmd_move,   "移動 F6"),
            ("📦", self.cmd_pack,  "圧縮 Alt+F5"),
            ("📁", self.cmd_mkdir, "新規Dir F7"),
        ]
        for sym, cmd, tip in btns:
            tk.Button(mid, text=sym, command=cmd,
                bg=C["mid_bg"], font=("Meiryo UI", 10),
                relief="flat", width=2, pady=2
            ).pack(pady=1, padx=1)

    def _build_cmdline(self):
        self.cmdline_frame = tk.Frame(self, bg=C["bar_bg"])
        if self.cfg.get("show_cmdline", True):
            self.cmdline_frame.pack(fill="x", side="bottom")
        tk.Label(self.cmdline_frame, text=">",
            bg=C["bar_bg"], fg=C["bar_fg"],
            font=("Meiryo UI", 10)).pack(side="left", padx=3)
        self.cmd_var = tk.StringVar()
        self.cmdline = tk.Entry(self.cmdline_frame, textvariable=self.cmd_var,
            bg="#FFFFF0", fg=C["panel_fg"],
            font=("Meiryo UI", 10), relief="sunken", bd=1)
        self.cmdline.pack(fill="x", expand=True, padx=2, pady=1)
        self.cmdline.bind("<Return>",  self._exec_cmd)
        self.cmdline.bind("<Escape>",  self._esc_cmd)
        self.cmdline.bind("<Tab>",     lambda e: (self.ap.tree.focus_set(), "break")[1])
        self.cmdline.bind("<FocusIn>", lambda _: None)

    def _build_fnbar(self):
        self.fnbar_frame = tk.Frame(self, bg=C["fnbar_bg"])
        if self.cfg.get("show_fnbar", True):
            self.fnbar_frame.pack(fill="x", side="bottom")
        fns = [
            ("F1","ヘルプ",    self.cmd_help),
            ("F2","更新",      lambda: self.ap.refresh()),
            ("F3","表示",      self.cmd_view),
            ("F4","編集",      self.cmd_edit),
            ("F5","コピー",    self.cmd_copy),
            ("F6","移動",      self.cmd_move),
            ("F7","新規Dir",   self.cmd_mkdir),
            ("F8","削除",      self.cmd_delete),
            ("F9","メニュー",  lambda: None),
            ("F10","終了",     self._close),
        ]
        for fk, lbl, cmd in fns:
            f = tk.Frame(self.fnbar_frame, bg=C["fnbar_bg"])
            f.pack(side="left", expand=True, fill="x")
            tk.Label(f, text=fk, bg=C["fnbar_bg"], fg=C["fnbar_num"],
                font=("Meiryo UI", 8, "bold")).pack(side="left")
            tk.Button(f, text=lbl, command=cmd, bg=C["fnbar_bg"],
                fg=C["fnbar_lbl"], relief="flat",
                font=("Meiryo UI", 8), bd=0).pack(side="left", fill="x", expand=True)

    def _build_statusbar(self):
        self.status_frame = tk.Frame(self, bg=C["bar_bg"], relief="sunken", bd=1)
        self.status_frame.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar()
        tk.Label(self.status_frame, textvariable=self.status_var,
            bg=C["bar_bg"], fg=C["bar_fg"],
            font=("Meiryo UI", 8), anchor="w").pack(fill="x", padx=4)

    def set_status(self, msg):
        self.title(f"{APP_NAME} — {msg}" if msg else APP_NAME)

    # ── パネル参照 ──
    @property
    def ap(self):
        return self.left if self._active_side == "left" else self.right

    @property
    def ip(self):
        return self.right if self._active_side == "left" else self.left

    def set_active(self, side):
        self._active_side = side
        self.left.set_active(side == "left")
        self.right.set_active(side == "right")

    def _disable_tab_focus(self):
        """Treeview以外の全ウィジェットをTab遷移の対象外にする"""
        exclude = {self.left.tree, self.right.tree}
        def walk(w):
            if w not in exclude:
                try: w.configure(takefocus=False)
                except: pass
            for child in w.winfo_children():
                walk(child)
        walk(self)

    def _switch_panel_from(self, from_panel):
        """Treeviewのウィジェット直バインドから呼ばれるパネル切替"""
        other = self.right if from_panel is self.left else self.left
        other_side = "right" if from_panel is self.left else "left"
        self.set_active(other_side)
        other.tree.focus_set()

    # ── キーバインド ──
    def _bind_keys(self):
        # メインウィンドウ以外 (ダイアログ等) からのイベントを無視するガード付き bind_all
        def ba(key, fn):
            def _guarded(event):
                try:
                    if event.widget.winfo_toplevel() is not self: return
                except Exception:
                    return
                return fn(event)
            self.bind_all(key, _guarded)

        # ファンクションキー
        ba("<F1>",  lambda e: self.cmd_help())
        ba("<F2>",  lambda e: self.ap.refresh())
        ba("<F3>",  lambda e: self.cmd_view())
        ba("<F4>",  lambda e: self.cmd_edit())
        ba("<Control-Return>", lambda e: self.cmd_vscode() or "break")
        ba("<F5>",  lambda e: self.cmd_copy())
        ba("<F6>",  lambda e: self.cmd_move())
        ba("<F7>",  lambda e: self.cmd_mkdir())
        ba("<F8>",  lambda e: self.cmd_delete())
        ba("<F10>", lambda e: self._close())
        # Shift+F*
        ba("<Shift-F2>",  lambda e: self.cmd_compare_dirs())
        ba("<Shift-F4>",  lambda e: self.cmd_new_file())
        ba("<Shift-F5>",  lambda e: self.cmd_copy_same())
        ba("<Shift-F6>",  lambda e: self.cmd_rename())
        ba("<Shift-F10>", lambda e: self.show_ctx_menu_kbd())
        # Alt+F*
        ba("<Alt-F1>",    lambda e: self.cmd_change_drive("left"))
        ba("<Alt-F2>",    lambda e: self.cmd_change_drive("right"))
        ba("<Alt-F4>",    lambda e: self._close())
        ba("<Alt-F5>",    lambda e: self.cmd_pack())
        ba("<Alt-F7>",    lambda e: self.cmd_find())
        ba("<Alt-F10>",   lambda e: self.cmd_cd_tree())
        # Ctrl+F*
        ba("<Control-F1>", lambda e: self.cmd_view_mode(True))
        ba("<Control-F2>", lambda e: self.cmd_view_mode(False))
        ba("<Control-F3>", lambda e: self.cmd_sort("name"))
        ba("<Control-F4>", lambda e: self.cmd_sort("ext"))
        ba("<Control-F5>", lambda e: self.cmd_sort("date"))
        ba("<Control-F6>", lambda e: self.cmd_sort("size"))
        ba("<Control-F7>", lambda e: self.cmd_sort("name"))  # unsorted -> name
        # Ctrl+文字
        ba("<Control-a>", lambda e: self.ap.select_all())
        ba("<Control-A>", lambda e: self.ap.select_all())
        ba("<Control-b>", lambda e: self.cmd_branch())
        ba("<Control-d>", lambda e: self.cmd_hotlist())
        ba("<Control-D>", lambda e: self.cmd_hotlist())
        ba("<Control-i>", lambda e: self.cmd_match_src())
        ba("<Control-I>", lambda e: self.cmd_match_src())
        ba("<Control-m>", lambda e: self.cmd_multi_rename())
        ba("<Control-M>", lambda e: self.cmd_multi_rename())
        ba("<Control-r>", lambda e: self.ap.refresh())
        ba("<Control-R>", lambda e: self.ap.refresh())
        ba("<Control-s>", lambda e: self.cmd_quick_filter())
        ba("<Control-S>", lambda e: self.cmd_quick_filter())
        ba("<Control-t>", lambda e: self.ap.new_tab())
        ba("<Control-T>", lambda e: self.ap.new_tab())
        ba("<Control-u>", lambda e: self.cmd_exchange())
        ba("<Control-U>", lambda e: self.cmd_exchange())
        ba("<Control-w>", lambda e: self.ap.close_tab())
        ba("<Control-W>", lambda e: self.ap.close_tab())
        ba("<Control-Tab>",         lambda e: self._next_tab())
        ba("<Control-Shift-Tab>",   lambda e: self._prev_tab())
        ba("<Control-BackSpace>",   lambda e: self._key_go_parent(e))
        ba("<Control-Prior>",       lambda e: self._key_go_parent(e))
        ba("<Control-backslash>",   lambda e: self.ap.go_root())
        # Ctrl+↓/↑ : コマンドライン操作
        ba("<Control-Down>", lambda e: self._focus_cmdline())
        ba("<Control-Up>",   lambda e: self._copy_name_to_cmdline())
        # Alt+方向キー
        ba("<Alt-Left>",   lambda e: self.cmd_back())
        ba("<Alt-Right>",  lambda e: self.cmd_forward())
        ba("<Alt-Return>", lambda e: self.cmd_properties())
        # Tab / 方向キー
        ba("<Tab>",        lambda e: self._key_tab(e))
        ba("<BackSpace>",  lambda e: self._key_go_parent(e))
        ba("<Return>",     lambda e: self._key_enter(e))
        ba("<Insert>",     lambda e: self._key_ins(e))
        ba("<space>",      lambda e: self._key_space(e))
        ba("<Delete>",     lambda e: self._key_del(e))
        ba("<Up>",    lambda e: self._key_nav(e, "up"))
        ba("<Down>",  lambda e: self._key_nav(e, "down"))
        ba("<Prior>", lambda e: self._key_nav(e, "pgup"))
        ba("<Next>",  lambda e: self._key_nav(e, "pgdn"))
        ba("<Home>",  lambda e: self._key_nav(e, "home"))
        ba("<End>",   lambda e: self._key_nav(e, "end"))
        # テンキー (Entryウィジェット内では無効)
        def _noentry(fn): return lambda e: None if self._is_input(e) else fn()
        ba("<KP_Add>",      _noentry(lambda: self.ap.select_by_pattern(True)))
        ba("<KP_Subtract>", _noentry(lambda: self.ap.select_by_pattern(False)))
        ba("<KP_Multiply>", _noentry(lambda: self.ap.invert_sel()))
        ba("<KP_Divide>",   _noentry(lambda: self.ap.restore_selection()))
        ba("<plus>",        _noentry(lambda: self.ap.select_by_pattern(True)))
        ba("<minus>",       _noentry(lambda: self.ap.select_by_pattern(False)))
        ba("<multiply>",    _noentry(lambda: self.ap.invert_sel()))
        ba("<Alt-KP_Add>",  _noentry(lambda: self.ap.select_same_ext(True)))
        ba("<Alt-KP_Subtract>", _noentry(lambda: self.ap.select_same_ext(False)))
        # クリップボード
        ba("<Control-c>",   lambda e: self._key_ctrl_c(e))
        ba("<Control-x>",   lambda e: self._key_ctrl_x(e))
        ba("<Control-v>",   lambda e: self._key_ctrl_v(e))
        # テキスト入力 → クイック検索
        ba("<Key>", self._key_char)

    def _is_input(self, event):
        return isinstance(event.widget, (tk.Entry, tk.Text))

    def _key_tab(self, event):
        if event.widget.winfo_toplevel() != self: return
        # Treeview以外 (ツールバーボタン等) からTabが来た場合はアクティブパネルに移動
        if event.widget not in (self.left.tree, self.right.tree):
            self.ap.tree.focus_set()
        return "break"

    def _focus_cmdline(self):
        """Ctrl+↓: コマンドラインへフォーカスを移す"""
        if not self.cfg.get("show_cmdline", True):
            return "break"
        self.cmdline.focus_set()
        self.cmdline.icursor(tk.END)
        return "break"

    def _copy_name_to_cmdline(self):
        """Ctrl+↑: カーソル下のファイル/ディレクトリ名をコマンドラインに挿入"""
        e = self.ap.cursor_entry()
        if not e: return "break"
        if not self.cfg.get("show_cmdline", True): return "break"
        name = e["name"]
        text = f'"{name}"' if " " in name else name
        self.cmdline.focus_set()
        pos = self.cmdline.index(tk.INSERT)
        self.cmdline.insert(pos, text)
        self.cmdline.icursor(tk.END)
        return "break"

    def _key_enter(self, event):
        if self._is_input(event): return
        try:
            if event.widget.winfo_toplevel() is not self: return
        except Exception:
            return
        self.ap.enter_cursor(); return "break"

    def _key_ins(self, event):
        if self._is_input(event): return
        self.ap.toggle_select(); return "break"

    def _key_space(self, event):
        if self._is_input(event): return
        self.ap.toggle_select(); return "break"

    def _key_del(self, event):
        if self._is_input(event): return
        self.cmd_delete(); return "break"

    def _key_go_parent(self, event):
        if self._is_input(event): return
        self.ap.go_parent(); return "break"

    def _key_nav(self, event, direction):
        if self._is_input(event): return
        self.ap.move_cursor(direction); return "break"

    def _key_char(self, event):
        if self._is_input(event): return
        ch = event.char
        if not ch or not ch.isprintable(): return
        if event.state & 0x4 or event.state & 0x20000: return  # Ctrl/Alt
        self.ap.quick_search(ch); return "break"

    def _key_ctrl_c(self, event):
        if self._is_input(event): return
        paths = self.ap.selected_paths()
        if paths:
            self.clipboard_clear()
            self.clipboard_append("\n".join(str(p) for p in paths))
        return "break"

    def _key_ctrl_x(self, event):
        if self._is_input(event): return
        self._key_ctrl_c(event)  # cut = copy then mark for move

    def _key_ctrl_v(self, event):
        if self._is_input(event): return
        return "break"  # paste from clipboard (file path) - complex to implement safely

    def _next_tab(self):
        p = self.ap
        if len(p.tabs) > 1: p._switch_tab((p.cur_tab + 1) % len(p.tabs))

    def _prev_tab(self):
        p = self.ap
        if len(p.tabs) > 1: p._switch_tab((p.cur_tab - 1) % len(p.tabs))

    # ── コマンドライン ──
    def _exec_cmd(self, _=None):
        cmd = self.cmd_var.get().strip()
        if not cmd: return
        cwd = str(self.ap.path)
        lo = cmd.lower()
        if lo.startswith("cd "):
            self.ap.goto(cmd[3:].strip())
        elif lo.startswith("md ") or lo.startswith("mkdir "):
            d = self.ap.path / cmd.split(None, 1)[1].strip()
            try: d.mkdir(parents=True, exist_ok=True); self.ap.refresh()
            except Exception as ex: messagebox.showerror("エラー", str(ex))
        elif lo.startswith("rd ") or lo.startswith("rmdir "):
            d = self.ap.path / cmd.split(None, 1)[1].strip()
            try: d.rmdir(); self.ap.refresh()
            except Exception as ex: messagebox.showerror("エラー", str(ex))
        else:
            try: subprocess.Popen(cmd, shell=True, cwd=cwd)
            except Exception as ex: messagebox.showerror("エラー", str(ex))
        self.cmd_var.set("")
        self.ap.tree.focus_set()

    def _esc_cmd(self, _=None):
        self.cmd_var.set("")
        self.ap.tree.focus_set()

    # ── ファイル操作コマンド ──
    def cmd_view(self):
        e = self.ap.cursor_entry()
        if e and not e["is_dir"]:
            viewer = self.cfg.get("viewer", "notepad")
            try: subprocess.Popen([viewer, e["path"]])
            except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_edit(self):
        e = self.ap.cursor_entry()
        if not e: return
        if e["is_dir"]: self.ap.goto(e["path"]); return
        editor = self.cfg.get("editor", "notepad")
        try: subprocess.Popen([editor, e["path"]])
        except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_vscode(self):
        paths = self.ap.selected_paths()
        if not paths: return
        venv_bases = self.cfg.get("venv_bases", [])
        activate = None  # 使用する activate.bat

        # ディレクトリ単体かつ venv_bases が設定済みの場合: 選択ダイアログを出す
        if len(paths) == 1 and paths[0].is_dir() and venv_bases:
            dlg = VenvSelectDialog(self, venv_bases)
            if dlg.result is None:   # キャンセル
                return
            if dlg.result is not False:
                activate = dlg.result

        if activate:
            cmd = f'cmd /c "call "{activate}" && code "{paths[0]}""'
            try:
                subprocess.Popen(cmd, shell=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception as ex:
                messagebox.showerror("エラー", str(ex))
        else:
            # 通常起動 (code は .cmd なので shell=True が必要)
            cmd = "code " + " ".join(f'"{p}"' for p in paths)
            try:
                subprocess.Popen(cmd, shell=True)
            except Exception as ex:
                messagebox.showerror("エラー", str(ex))

    def cmd_new_file(self):
        name = simpledialog.askstring("新規ファイル (Shift+F4)", "ファイル名:", parent=self)
        if not name: return
        p = self.ap.path / name
        try:
            p.touch()
            self.ap.refresh()
            subprocess.Popen([self.cfg.get("editor","notepad"), str(p)])
        except Exception as ex: messagebox.showerror("エラー", str(ex))

    def _do_copy_move(self, move=False):
        src_panel = self.ap   # ダイアログ表示前に固定 (フォーカス移動で _active_side がずれても安全)
        dst_panel = self.ip
        srcs = src_panel.selected_paths()
        if not srcs: return
        dlg = CopyMoveDialog(self, srcs, dst_panel.path, move=move)
        if not dlg.result: return
        dest = Path(dlg.result)
        if not dest.exists():
            try: dest.mkdir(parents=True)
            except Exception as ex: messagebox.showerror("エラー", str(ex)); return
        errs = []
        for s in srcs:
            self.title(f"{APP_NAME} — {'移動' if move else 'コピー'}中: {s.name}")
            self.update_idletasks()
            try:
                d = dest / s.name
                if s.is_dir():
                    shutil.move(str(s), str(d)) if move else shutil.copytree(str(s), str(d), dirs_exist_ok=True)
                else:
                    shutil.move(str(s), str(d)) if move else shutil.copy2(str(s), str(d))
            except Exception as ex: errs.append(f"{s.name}: {ex}")
        self.title(APP_NAME)
        src_panel.refresh(); dst_panel.refresh()
        src_panel.deselect_all()
        if errs: messagebox.showerror("エラー", "\n".join(errs[:10]))

    def cmd_copy(self): self._do_copy_move(move=False)
    def cmd_move(self): self._do_copy_move(move=True)

    def cmd_copy_same(self):
        e = self.ap.cursor_entry()
        if not e or e["is_dir"]: return
        dlg = RenameDialog(self, e["name"])
        if dlg.result and dlg.result != e["name"]:
            src = Path(e["path"])
            try: shutil.copy2(str(src), str(src.parent / dlg.result)); self.ap.refresh()
            except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_rename(self):
        e = self.ap.cursor_entry()
        if not e: return
        dlg = RenameDialog(self, e["name"])
        if dlg.result and dlg.result != e["name"]:
            src = Path(e["path"])
            try: src.rename(src.parent / dlg.result); self.ap.refresh()
            except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_mkdir(self):
        panel = self.ap
        target_dir = panel.path  # ダイアログを開く前にパスを固定
        dlg = MkdirDialog(self)
        if dlg.result:
            p = target_dir / dlg.result
            try: p.mkdir(parents=True, exist_ok=True); panel.refresh()
            except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_delete(self):
        panel = self.ap   # 確認ダイアログ前に固定
        srcs = panel.selected_paths()
        if not srcs: return
        names = "\n".join(p.name for p in srcs[:8]) + ("..." if len(srcs) > 8 else "")
        if not messagebox.askyesno("削除確認",
                f"{len(srcs)} 件をごみ箱へ移動しますか?\n\n{names}"): return
        errs = []
        for p in srcs:
            try:
                _send_to_trash(str(p))
            except Exception as ex: errs.append(f"{p.name}: {ex}")
        panel.refresh(); panel.deselect_all()
        if errs: messagebox.showerror("エラー", "\n".join(errs[:10]))

    def cmd_set_attr(self):
        e = self.ap.cursor_entry()
        if not e: return
        messagebox.showinfo("属性変更", f"ファイル: {e['name']}\n\n(属性変更はOS依存のため、エクスプローラーでの操作を推奨します)")

    def cmd_properties(self):
        e = self.ap.cursor_entry()
        if not e: return
        p = Path(e["path"])
        try:
            st = p.stat()
            info = (f"名前: {p.name}\n"
                    f"パス: {p.parent}\n"
                    f"サイズ: {st.st_size:,} バイト ({fmt_size(st.st_size)})\n"
                    f"更新日時: {fmt_date(st.st_mtime)}\n"
                    f"作成日時: {fmt_date(st.st_ctime)}\n"
                    f"種類: {'ディレクトリ' if p.is_dir() else 'ファイル'}\n"
                    f"属性: {fmt_attr(e['path'])}")
            messagebox.showinfo(f"プロパティ: {p.name}", info)
        except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_pack(self):
        srcs = self.ap.selected_paths()
        if not srcs: return
        name = simpledialog.askstring("圧縮 (Alt+F5)", "アーカイブ名 (.zip):",
            initialvalue=srcs[0].stem + ".zip", parent=self)
        if not name: return
        if not name.endswith(".zip"): name += ".zip"
        out = self.ap.path / name
        try:
            with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
                for s in srcs:
                    if s.is_dir():
                        for f in s.rglob("*"):
                            zf.write(str(f), str(f.relative_to(s.parent)))
                    else:
                        zf.write(str(s), s.name)
            self.ap.refresh()
            messagebox.showinfo("完了", f"{out.name} を作成しました")
        except Exception as ex: messagebox.showerror("エラー", str(ex))

    # ── ナビゲーションコマンド ──
    def cmd_back(self):    self.ap.go_back()
    def cmd_forward(self): self.ap.go_forward()

    def cmd_exchange(self):
        lp, rp = str(self.left.path), str(self.right.path)
        self.left.goto(rp); self.right.goto(lp)

    def cmd_match_src(self):
        self.ip.goto(str(self.ap.path))

    def cmd_change_drive(self, side):
        panel = self.left if side == "left" else self.right
        drives = get_drives()
        if not drives: return

        top = tk.Toplevel(self)
        top.title(f"ドライブ変更 ({'左' if side == 'left' else '右'})")
        top.resizable(False, False)
        top.transient(self)

        lb = tk.Listbox(top, font=("Meiryo UI", 10),
                        selectmode="single", exportselection=False,
                        selectbackground=C["cursor_bg"],
                        selectforeground=C["cursor_fg"],
                        activestyle="none",
                        width=30, height=min(len(drives), 12))
        for d in drives:
            free_k, _ = disk_free(d + "\\")
            lb.insert(tk.END, f"  {d}  ({free_k:,} k free)")
        lb.selection_set(0)
        lb.activate(0)
        lb.pack(padx=8, pady=8)

        def go(_=None):
            sel = lb.curselection()
            idx = sel[0] if sel else lb.index(tk.ACTIVE)
            d = drives[idx]
            top.destroy()
            panel.goto(d + "\\")
            panel.tree.focus_set()

        def sync_sel(e=None):
            lb.after(0, lambda: (
                lb.selection_clear(0, tk.END),
                lb.selection_set(lb.index(tk.ACTIVE))
            ))

        def jump_letter(event):
            ch = event.char.upper()
            if not ch.isalpha(): return
            for i, d in enumerate(drives):
                if d.upper().startswith(ch):
                    lb.selection_clear(0, tk.END)
                    lb.selection_set(i)
                    lb.activate(i)
                    lb.see(i)
                    break
            return "break"

        lb.bind("<Up>",              sync_sel)
        lb.bind("<Down>",            sync_sel)
        lb.bind("<Return>",          go)
        lb.bind("<Double-Button-1>", go)
        lb.bind("<Key>",             jump_letter)
        top.bind("<Escape>",         lambda _: top.destroy())
        lb.focus_set()
        top.grab_set()

    def cmd_cd_tree(self):
        top = tk.Toplevel(self)
        top.title("ディレクトリツリー (Alt+F10)")
        top.geometry("400x500")
        tv = ttk.Treeview(top, show="tree")
        sb = tk.Scrollbar(top, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); tv.pack(fill="both", expand=True)
        root = str(self.ap.path.anchor)
        root_node = tv.insert("", "end", text=root, open=True)
        def add_children(node, path):
            try:
                for e in sorted(os.scandir(path), key=lambda x: x.name.lower()):
                    if e.is_dir():
                        n = tv.insert(node, "end", text=e.name)
                        tv.insert(n, "end", text="...")  # lazy load
            except: pass
        add_children(root_node, root)
        def on_expand(event):
            node = tv.focus()
            children = tv.get_children(node)
            if len(children) == 1 and tv.item(children[0])["text"] == "...":
                tv.delete(children[0])
                full = _get_full_path(node)
                add_children(node, full)
        def _get_full_path(node):
            parts = []
            while node:
                parts.append(tv.item(node)["text"])
                node = tv.parent(node)
            parts.reverse()
            return os.path.join(*parts)
        tv.bind("<<TreeviewOpen>>", on_expand)
        def go_selected(_=None):
            node = tv.focus()
            if node:
                p = _get_full_path(node)
                self.ap.goto(p); top.destroy()
        tv.bind("<Double-Button-1>", go_selected)
        tv.bind("<Return>", go_selected)
        tk.Button(top, text="移動", command=go_selected).pack(pady=4)
        top.grab_set()

    # ── ツールコマンド ──
    def cmd_find(self):
        FindDialog(self, self.ap.path)

    def cmd_multi_rename(self):
        srcs = self.ap.selected_paths()
        if not srcs:
            e = self.ap.cursor_entry()
            if e: srcs = [Path(e["path"])]
        if srcs:
            MultiRenameDialog(self, srcs)
            self.ap.refresh()

    def cmd_hotlist(self):
        panel   = self.ap
        inactive = self.ip
        def on_goto(path, target=None):
            panel.goto(path)
            if target:
                inactive.goto(target)
        HotlistMenu(self, self.cfg["hotlist"],
                    panel.path, inactive.path,
                    on_goto,
                    lambda: save_cfg(self.cfg))
        save_cfg(self.cfg)

    def cmd_compare_dirs(self):
        left_names  = {e["name"] for e in self.left.entries}
        right_names = {e["name"] for e in self.right.entries}
        only_l = left_names - right_names
        only_r = right_names - left_names
        common = left_names & right_names
        top = tk.Toplevel(self); top.title("ディレクトリ比較 (Shift+F2)")
        top.geometry("640x450")
        t = tk.Text(top, font=("Meiryo UI", 9), wrap="none")
        sb_y = tk.Scrollbar(top, command=t.yview)
        t.configure(yscrollcommand=sb_y.set)
        sb_y.pack(side="right", fill="y"); t.pack(fill="both", expand=True, padx=4, pady=4)
        t.tag_config("hdr", foreground="#000080", font=("Meiryo UI", 9, "bold"))
        t.tag_config("left", foreground="#AA0000")
        t.tag_config("right", foreground="#006600")
        t.insert("end", f"=== 左のみ ({len(only_l)}件) ===\n", "hdr")
        for n in sorted(only_l): t.insert("end", f"  {n}\n", "left")
        t.insert("end", f"\n=== 右のみ ({len(only_r)}件) ===\n", "hdr")
        for n in sorted(only_r): t.insert("end", f"  {n}\n", "right")
        t.insert("end", f"\n=== 共通 ({len(common)}件) ===\n", "hdr")
        for n in sorted(common): t.insert("end", f"  {n}\n")
        t.configure(state="disabled")

    def cmd_branch(self):
        """Ctrl+B: ブランチビュー (全サブディレクトリのファイルを一覧)"""
        panel = self.ap
        all_files = []
        try:
            for p in Path(panel.path).rglob("*"):
                if p.is_file():
                    try:
                        st = p.stat()
                        all_files.append({
                            "name": str(p.relative_to(panel.path)),
                            "ext": p.suffix.lstrip("."),
                            "size": st.st_size,
                            "mtime": st.st_mtime,
                            "is_dir": False, "is_link": p.is_symlink(),
                            "path": str(p),
                        })
                    except: pass
        except: pass
        panel.entries = sort_entries(all_files, panel.sort_col, panel.sort_rev)
        panel._populate()
        panel._update_status()
        panel.path_var.set(f"{panel.path}  [ブランチビュー]")

    def cmd_sort(self, col):     self.ap._click_header(col)
    def cmd_view_mode(self, brief): self.ap.set_brief(brief)
    def cmd_quick_filter(self):  self.ap._change_filter()

    def cmd_toggle_hidden(self):
        self.cfg["show_hidden"] = not self.cfg.get("show_hidden", True)
        self.left.refresh(); self.right.refresh()

    def cmd_copy_names(self):
        names = [p.name for p in self.ap.selected_paths()]
        if names: self.clipboard_clear(); self.clipboard_append("\n".join(names))

    def cmd_copy_full_names(self):
        paths = [str(p) for p in self.ap.selected_paths()]
        if paths: self.clipboard_clear(); self.clipboard_append("\n".join(paths))

    def cmd_terminal(self):
        try: subprocess.Popen("cmd.exe", cwd=str(self.ap.path))
        except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_terminal_ps(self):
        try: subprocess.Popen(["powershell.exe"], cwd=str(self.ap.path))
        except Exception as ex: messagebox.showerror("エラー", str(ex))

    def cmd_cfg_location(self):
        """設定ファイルの保存先フォルダを変更する"""
        global CONFIG_FILE
        from tkinter import filedialog
        d = filedialog.askdirectory(
            title="設定ファイルの保存先フォルダを選択",
            initialdir=str(CONFIG_FILE.parent))
        if not d:
            return
        new_file = Path(d) / "launcher_tc.json"
        if new_file == CONFIG_FILE:
            return
        try:
            # 現在の設定を新しい場所にコピーしてから切り替え
            new_file.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2), "utf-8")
            old = CONFIG_FILE
            CONFIG_FILE = new_file
            messagebox.showinfo("設定ファイルの場所",
                f"保存先を変更しました。\n\n"
                f"旧: {old}\n"
                f"新: {CONFIG_FILE}\n\n"
                "スクリプト横 (launcher_tc.json) を選んだ場合、\n"
                "次回起動から自動的にその場所が使われます。")
        except Exception as ex:
            messagebox.showerror("エラー", str(ex))

    def cmd_cfg_editor(self):
        e = simpledialog.askstring("エディタ設定",
            "エディタの実行ファイル名:", initialvalue=self.cfg.get("editor","notepad"), parent=self)
        if e: self.cfg["editor"] = e; save_cfg(self.cfg)

    def cmd_cfg_venv(self):
        dlg = VenvBasesDialog(self, self.cfg.get("venv_bases", []))
        if dlg.result is not None:
            self.cfg["venv_bases"] = dlg.result
            save_cfg(self.cfg)

    def cmd_toggle_cmdline(self):
        self.cfg["show_cmdline"] = not self.cfg.get("show_cmdline", True)
        if self.cfg["show_cmdline"]: self.cmdline_frame.pack(fill="x", side="bottom", before=self.fnbar_frame)
        else: self.cmdline_frame.pack_forget()

    def cmd_toggle_fnbar(self):
        self.cfg["show_fnbar"] = not self.cfg.get("show_fnbar", True)
        if self.cfg["show_fnbar"]: self.fnbar_frame.pack(fill="x", side="bottom")
        else: self.fnbar_frame.pack_forget()

    def cmd_help(self):
        top = tk.Toplevel(self); top.title("ヘルプ - キーボードショートカット")
        top.geometry("680x520")
        t = tk.Text(top, font=("Meiryo UI", 9), wrap="none", bg="#FFFFFE")
        sb = tk.Scrollbar(top, command=t.yview); t.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); t.pack(fill="both", expand=True, padx=4, pady=4)
        t.insert("end", HELP_TEXT); t.configure(state="disabled")

    def show_ctx_menu(self, event):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="表示 (F3)",                   command=self.cmd_view)
        m.add_command(label="編集 (F4)",                   command=self.cmd_edit)
        m.add_command(label="VSCodeで開く (Ctrl+Enter)",   command=self.cmd_vscode)
        m.add_separator()
        m.add_command(label="コピー (F5)",         command=self.cmd_copy)
        m.add_command(label="移動 (F6)",           command=self.cmd_move)
        m.add_command(label="リネーム (Shift+F6)", command=self.cmd_rename)
        m.add_command(label="削除 (F8)",           command=self.cmd_delete)
        m.add_separator()
        m.add_command(label="新規フォルダ (F7)",   command=self.cmd_mkdir)
        m.add_command(label="圧縮 (Alt+F5)",       command=self.cmd_pack)
        m.add_separator()
        m.add_command(label="プロパティ (Alt+Enter)", command=self.cmd_properties)
        m.add_command(label="コマンドプロンプトを開く", command=self.cmd_terminal)
        try: m.tk_popup(event.x_root, event.y_root)
        finally: m.grab_release()

    def show_ctx_menu_kbd(self):
        class E:
            x_root = 500; y_root = 400
        self.show_ctx_menu(E())

    def _close(self):
        self.cfg["left_path"]  = str(self.left.path)
        self.cfg["right_path"] = str(self.right.path)
        self.cfg["geometry"]   = self.geometry()
        save_cfg(self.cfg)
        self.destroy()

# ── ヘルプテキスト ──────────────────────────────────
HELP_TEXT = """
Launcher - Python Total Commander互換ファイルマネージャー
=========================================================

【基本ナビゲーション】
  Tab              左右パネル切替
  Enter            ディレクトリを開く / ファイルを実行
  Backspace        親ディレクトリへ (Ctrl+PgUp も同じ)
  Ctrl+\\           ルートへ
  Alt+Left/Right   戻る / 進む (ディレクトリ履歴)
  Alt+Down         ディレクトリ履歴リスト
  Alt+F10          ディレクトリツリーポップアップ

【ファイル操作】
  F3               表示 (ビューア)
  F4               編集 (エディタ)
  F5               コピー
  F6               移動 / リネーム
  F7               新規ディレクトリ作成
  F8 / Delete      削除
  Shift+F4         新規ファイル作成・編集
  Shift+F5         同一ディレクトリにコピー
  Shift+F6         リネーム (同ディレクトリ内)
  Alt+F5           圧縮 (ZIP)

【選択】
  Insert / Space   カーソル行の選択トグル
  Ctrl+A           全選択
  Num + (テンキー) パターンで選択
  Num - (テンキー) パターンで選択解除
  Num * (テンキー) 選択反転
  Num / (テンキー) 保存した選択を復元
  Alt+Num+         同拡張子を選択
  Alt+Num-         同拡張子を選択解除

【ソート・表示】
  Ctrl+F1          簡易表示 (名前のみ)
  Ctrl+F2          詳細表示 (名前/拡張子/サイズ/日時/属性)
  Ctrl+F3          名前順
  Ctrl+F4          拡張子順
  Ctrl+F5          更新日時順
  Ctrl+F6          サイズ順
  ヘッダークリック  その列でソート (再クリックで逆順)

【タブ】
  Ctrl+T           新規タブ
  Ctrl+W           タブを閉じる
  Ctrl+Tab         次のタブへ
  Ctrl+Shift+Tab   前のタブへ

【パネル操作】
  Ctrl+U           左右ディレクトリを交換
  Ctrl+I           ターゲット = ソース
  Alt+F1           左パネルのドライブ変更
  Alt+F2           右パネルのドライブ変更

【ツール】
  Alt+F7           ファイル検索
  Ctrl+M           一括リネームツール
  Ctrl+D           ディレクトリホットリスト (ブックマーク)
  Shift+F2         ディレクトリ比較
  Ctrl+B           ブランチビュー (サブディレクトリも一覧)
  Ctrl+S           クイックフィルター
  Alt+Enter        プロパティ表示

【クリップボード】
  Ctrl+C           選択ファイルのパスをクリップボードにコピー

【コマンドライン (画面下部)】
  文字入力         クイック検索 (1.5秒でリセット)
  > プロンプト     コマンド実行 (cd / md / rd / 任意コマンド)
  Escape           コマンドラインをクリア
"""

# ── エントリポイント ─────────────────────────────────
def main():
    left  = sys.argv[1] if len(sys.argv) > 1 else None
    right = sys.argv[2] if len(sys.argv) > 2 else None
    app = App(left, right)
    app.mainloop()

if __name__ == "__main__":
    main()
