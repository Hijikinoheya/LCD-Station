import json
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class Debouncer:
    def __init__(self, widget: tk.Widget, delay_ms: int, callback):
        self.widget = widget
        self.delay_ms = delay_ms
        self.callback = callback
        self._after_id = None

    def trigger(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.widget.after(self.delay_ms, self._run)

    def _run(self):
        self._after_id = None
        try:
            self.callback()
        except Exception:
            pass


DEFAULT_COLUMNS = [
    "time",
    "destination",
    "line",
    "platform",
    "type",
    "via",
    "stops",  # カンマ区切り文字列 <-> 配列
    "pass_through",  # チェックボックス相当
    "delay_secs",
]


def dict_union_keys(records):
    keys = []
    seen = set()
    for r in records:
        for k in r.keys():
            if k not in seen:
                keys.append(k)
                seen.add(k)
    return keys


class JsonTableEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("電車発車JSONエディタ")
        self.geometry("1100x600")

        self.current_path = None
        self.records = []  # list[dict]

        self._build_menu()
        self._build_toolbar()
        self._build_table()
        self._build_status()

        self._editing_entry = None
        self._editing_cell = None  # (item_id, column_id)

        self.autosave = Debouncer(self, 1200, self._auto_save_if_possible)

        self._initial_load()

    # UI
    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="新規", command=self.new_file)
        file_menu.add_command(label="開く...", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="上書き保存", command=self.save_file)
        file_menu.add_command(label="名前を付けて保存...", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="終了", command=self.destroy)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="行を追加", command=self.add_row)
        edit_menu.add_command(label="行を削除", command=self.delete_selected_rows)
        edit_menu.add_command(label="列を削除...", command=self.delete_column_dialog)

        menubar.add_cascade(label="ファイル", menu=file_menu)
        menubar.add_cascade(label="編集", menu=edit_menu)
        self.config(menu=menubar)

    def _build_toolbar(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(bar, text="新規", command=self.new_file).pack(side=tk.LEFT, padx=2, pady=4)
        ttk.Button(bar, text="開く", command=self.open_file).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="保存", command=self.save_file).pack(side=tk.LEFT, padx=2)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="行追加", command=self.add_row).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="行削除", command=self.delete_selected_rows).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="列削除", command=self.delete_column_dialog).pack(side=tk.LEFT, padx=2)

        # ---- Delay / Pass-through quick controls ----
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(bar, text="遅延").pack(side=tk.LEFT, padx=(4, 2))
        self.delay_min_var = tk.StringVar(value="0")
        self.delay_sec_var = tk.StringVar(value="0")
        min_box = ttk.Spinbox(bar, from_=0, to=600, width=4, textvariable=self.delay_min_var)
        sec_box = ttk.Spinbox(bar, from_=0, to=59, width=4, textvariable=self.delay_sec_var)
        ttk.Label(bar, text="分").pack(side=tk.LEFT)
        min_box.pack(side=tk.LEFT)
        ttk.Label(bar, text="秒").pack(side=tk.LEFT)
        sec_box.pack(side=tk.LEFT)
        ttk.Button(bar, text="適用", command=self.apply_delay_to_selection).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(bar, text="遅延クリア", command=self.clear_delay_on_selection).pack(side=tk.LEFT, padx=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(bar, text="通過にする", command=lambda: self.set_pass_through_on_selection(True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="通過解除", command=lambda: self.set_pass_through_on_selection(False)).pack(side=tk.LEFT, padx=2)

    def _build_table(self):
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(container, columns=DEFAULT_COLUMNS, show="headings", selectmode="extended")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        for col in DEFAULT_COLUMNS:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor=tk.W)

        # イベント
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-1>", self._on_single_click)

    def _build_status(self):
        self.status_var = tk.StringVar(value="準備完了")
        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bar, textvariable=self.status_var, anchor=tk.W).pack(side=tk.LEFT, padx=8, pady=2)

    # Data IO
    def _initial_load(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for candidate in ("departures.json", "test.json"):
            path = os.path.join(base_dir, candidate)
            if os.path.exists(path):
                try:
                    self.load_from_path(path)
                    return
                except Exception:
                    pass
        # 見つからない場合は新規
        self.new_file()

    def new_file(self):
        self.current_path = None
        self.records = []
        self._refresh_columns(DEFAULT_COLUMNS)
        self._reload_table()
        self._set_status("新規ドキュメント")

    def open_file(self):
        path = filedialog.askopenfilename(
            title="JSONを開く",
            filetypes=[("JSONファイル", "*.json"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            self.load_from_path(path)
        except Exception as e:
            messagebox.showerror("読み込みエラー", str(e))

    def load_from_path(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        recs = data.get("departures", [])
        if not isinstance(recs, list):
            raise ValueError("'departures' は配列である必要があります")
        # JSONの値が空でも通す: そのまま保持
        self.records = []
        for r in recs:
            if not isinstance(r, dict):
                continue
            self.records.append(dict(r))
        # 列はデータのユニオン
        cols = dict_union_keys(self.records)
        if not cols:
            cols = DEFAULT_COLUMNS
        else:
            # 使い勝手向上のため既定列順を優先し、未知キーは後ろに並べる
            ordered = [c for c in DEFAULT_COLUMNS if c in cols]
            extras = [c for c in cols if c not in DEFAULT_COLUMNS]
            cols = ordered + extras

        self._refresh_columns(cols)
        self._reload_table()
        self.current_path = path
        self._set_status(f"読み込み: {os.path.basename(path)}")

    def save_file(self):
        if not self.current_path:
            return self.save_file_as()
        self._save_to_path(self.current_path)

    def save_file_as(self):
        path = filedialog.asksaveasfilename(
            title="名前を付けて保存",
            defaultextension=".json",
            filetypes=[("JSONファイル", "*.json"), ("すべて", "*.*")],
        )
        if not path:
            return
        self._save_to_path(path)
        self.current_path = path

    def _save_to_path(self, path: str):
        try:
            data = {"departures": self._collect_records_from_tree()}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._set_status(f"保存: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("保存エラー", str(e))

    def _auto_save_if_possible(self):
        if self.current_path:
            try:
                data = {"departures": self._collect_records_from_tree()}
                with open(self.current_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self._set_status("自動保存しました")
            except Exception:
                # 自動保存は失敗しても致命的ではない
                pass

    # Table helpers
    def _refresh_columns(self, columns):
        # 既存列を置換
        self.tree["columns"] = columns
        for c in columns:
            if self.tree.heading(c, option="text") == "":
                self.tree.heading(c, text=c)
            self.tree.column(c, width=120, anchor=tk.W)

    def _ensure_column(self, col: str):
        cols = list(self.tree["columns"])
        if col not in cols:
            cols.append(col)
            self._refresh_columns(cols)
            # 既存行に空値を補う
            for iid in self.tree.get_children():
                vals = list(self.tree.item(iid, "values"))
                # 足りない分だけ空欄を追加
                while len(vals) < len(cols):
                    vals.append("")
                self.tree.item(iid, values=vals)

    def _reload_table(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.records:
            values = []
            for c in self.tree["columns"]:
                if c == "pass_through":
                    v = r.get(c, False)
                    values.append("✓" if bool(v) else "")
                elif c == "stops":
                    v = r.get(c, [])
                    if isinstance(v, list):
                        values.append(", ".join(str(x) for x in v))
                    else:
                        values.append(str(v) if v is not None else "")
                else:
                    v = r.get(c, "")
                    values.append("" if v is None else str(v))
            self.tree.insert("", tk.END, values=values)

    def _collect_records_from_tree(self):
        columns = list(self.tree["columns"])  # 型: list[str]
        out = []
        for item_id in self.tree.get_children():
            row = {}
            vals = self.tree.item(item_id, "values")
            for idx, c in enumerate(columns):
                cell = vals[idx] if idx < len(vals) else ""
                if c == "pass_through":
                    if cell in ("✓", True, "True", "true", 1, "1"):
                        row[c] = True
                    # 未チェックはキー省略
                elif c == "stops":
                    if isinstance(cell, str):
                        s = cell.strip()
                        if s:
                            parts = [p.strip() for p in s.split(",")]
                            parts = [p for p in parts if p]
                            if parts:
                                row[c] = parts
                    elif isinstance(cell, list):
                        if cell:
                            row[c] = cell
                elif c == "delay_secs":
                    s = str(cell).strip()
                    if s:
                        try:
                            row[c] = int(s)
                        except ValueError:
                            # 数値でなければ文字列として保持
                            row[c] = s
                    # 空は省略
                else:
                    # 文字列列は空でも保存
                    row[c] = str(cell) if cell is not None else ""
            out.append(row)
        return out

    # Row/Column operations
    def add_row(self):
        empty = []
        for c in self.tree["columns"]:
            empty.append("" if c != "pass_through" else "")
        self.tree.insert("", tk.END, values=empty)
        self.autosave.trigger()

    def delete_selected_rows(self):
        sel = self.tree.selection()
        if not sel:
            return
        for iid in sel:
            self.tree.delete(iid)
        self.autosave.trigger()

    def delete_column_dialog(self):
        cols = list(self.tree["columns"])
        if not cols:
            return

        win = tk.Toplevel(self)
        win.title("列を削除")
        ttk.Label(win, text="削除する列を選択").pack(padx=10, pady=6)
        var = tk.StringVar(value=cols[0])
        box = ttk.Combobox(win, values=cols, textvariable=var, state="readonly")
        box.pack(padx=10, pady=6)

        def do_delete():
            col = var.get()
            self._delete_column(col)
            win.destroy()

        ttk.Button(win, text="削除", command=do_delete).pack(padx=10, pady=10)

    def _delete_column(self, col: str):
        if col not in self.tree["columns"]:
            return
        # 値から該当列を除去
        idx = list(self.tree["columns"]).index(col)
        for iid in self.tree.get_children():
            vals = list(self.tree.item(iid, "values"))
            if idx < len(vals):
                del vals[idx]
                self.tree.item(iid, values=vals)
        # 列リスト更新
        new_cols = [c for c in self.tree["columns"] if c != col]
        self._refresh_columns(new_cols)
        # 見出しを再設定
        for c in new_cols:
            self.tree.heading(c, text=c)
        self.autosave.trigger()

    # ---- Quick actions: delay / pass_through ----
    def apply_delay_to_selection(self):
        self._ensure_column("delay_secs")
        try:
            minutes = int(str(self.delay_min_var.get()).strip() or 0)
        except ValueError:
            minutes = 0
        try:
            seconds = int(str(self.delay_sec_var.get()).strip() or 0)
        except ValueError:
            seconds = 0
        total = max(0, minutes * 60 + seconds)
        sel = self.tree.selection()
        if not sel:
            return
        cols = list(self.tree["columns"])
        try:
            idx = cols.index("delay_secs")
        except ValueError:
            return
        for iid in sel:
            vals = list(self.tree.item(iid, "values"))
            while len(vals) < len(cols):
                vals.append("")
            vals[idx] = str(total)
            self.tree.item(iid, values=vals)
        self.autosave.trigger()

    def clear_delay_on_selection(self):
        self._ensure_column("delay_secs")
        sel = self.tree.selection()
        if not sel:
            return
        cols = list(self.tree["columns"])
        try:
            idx = cols.index("delay_secs")
        except ValueError:
            return
        for iid in sel:
            vals = list(self.tree.item(iid, "values"))
            while len(vals) < len(cols):
                vals.append("")
            vals[idx] = ""
            self.tree.item(iid, values=vals)
        self.autosave.trigger()

    def set_pass_through_on_selection(self, flag: bool):
        self._ensure_column("pass_through")
        sel = self.tree.selection()
        if not sel:
            return
        cols = list(self.tree["columns"])
        try:
            idx = cols.index("pass_through")
        except ValueError:
            return
        mark = "✓" if flag else ""
        for iid in sel:
            vals = list(self.tree.item(iid, "values"))
            while len(vals) < len(cols):
                vals.append("")
            vals[idx] = mark
            self.tree.item(iid, values=vals)
        self.autosave.trigger()

    # Editing handlers
    def _on_single_click(self, event):
        # 編集中のEntryを確定
        if self._editing_entry is not None:
            self._finalize_edit()

    def _on_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)  # '#1' ベース
        if not row_id or not col_id:
            return

        col_index = int(col_id.replace("#", "")) - 1
        columns = list(self.tree["columns"])
        if col_index < 0 or col_index >= len(columns):
            return
        column_name = columns[col_index]

        if column_name == "pass_through":
            # チェックボックス風トグル
            values = list(self.tree.item(row_id, "values"))
            cur = values[col_index] if col_index < len(values) else ""
            values[col_index] = "" if cur == "✓" else "✓"
            self.tree.item(row_id, values=values)
            self.autosave.trigger()
            return

        # セル編集: Entry配置
        bbox = self.tree.bbox(row_id, column=col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        value = self.tree.set(row_id, column=column_name)

        entry = ttk.Entry(self.tree)
        entry.insert(0, value)
        entry.select_range(0, tk.END)
        entry.focus_set()
        entry.place(x=x, y=y, width=w, height=h)

        entry.bind("<Return>", lambda e: self._finalize_edit())
        entry.bind("<Escape>", lambda e: self._cancel_edit())
        entry.bind("<FocusOut>", lambda e: self._finalize_edit())

        self._editing_entry = entry
        self._editing_cell = (row_id, column_name)

    def _finalize_edit(self):
        if not self._editing_entry or not self._editing_cell:
            return
        value = self._editing_entry.get()
        row_id, column_name = self._editing_cell
        self.tree.set(row_id, column=column_name, value=value)
        self._editing_entry.destroy()
        self._editing_entry = None
        self._editing_cell = None
        self.autosave.trigger()

    def _cancel_edit(self):
        if not self._editing_entry:
            return
        self._editing_entry.destroy()
        self._editing_entry = None
        self._editing_cell = None

    def _set_status(self, text: str):
        self.status_var.set(text)


def main():
    app = JsonTableEditor()
    app.mainloop()


if __name__ == "__main__":
    main()


