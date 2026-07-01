#!/usr/bin/env python3
"""Budget tracker GUI.

A self-contained Tkinter application that stores data in its own SQLite
database (``budget.db``). The schema mirrors ``budget.sql`` (a MariaDB dump):

  * ``budget_items`` -- id, category (the spending categories)
  * ``budget_lines`` -- id, store, price, date, category (FK -> budget_items)

The window has two tabs:
  * "Data"  -- add / edit / delete budget lines.
  * "Chart" -- a column graph of total spend (GBP) grouped by category,
               year, or three-letter month name.

The bar chart is drawn directly on a Tkinter Canvas, so the only requirement
is a standard Python install with Tk (no third-party packages needed).
"""

import os
import sqlite3
import threading
import datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox

# pyttsx3 powers the "read chart aloud" feature for visually impaired users.
# It is optional: if it is not installed the app still runs, and the speech
# controls explain how to enable it.
try:
    import pyttsx3
except ImportError:  # pragma: no cover - depends on the environment
    pyttsx3 = None

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "budget.db")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Categories seeded from budget.sql (id -> category). Ids are preserved so the
# SQLite database matches the original MariaDB data.
SEED_CATEGORIES = [
    (20, "Household Stuff"),
    (21, "Food/Drink"),
    (22, "Utilities/Bills"),
    (23, "Entertainment"),
    (25, "Web Services"),
    (28, "Healthcare"),
    (31, "Transport"),
    (32, "Accommodation"),
]


def gbp(value):
    """Format a number as pounds sterling, e.g. 1234.5 -> '£1,234.50'."""
    return "£{:,.2f}".format(value)


def spoken_gbp(value):
    """Format a number as words a screen reader / TTS can pronounce clearly.

    e.g. 1234.5 -> '1234 pounds and 50 pence'.
    """
    pounds = int(value)
    pence = int(round((value - pounds) * 100))
    if pence == 100:  # rounding pushed us to the next pound
        pounds += 1
        pence = 0
    text = "{} pound{}".format(pounds, "" if pounds == 1 else "s")
    if pence:
        text += " and {} pence".format(pence)
    return text


# --------------------------------------------------------------------------- #
# Text to speech
# --------------------------------------------------------------------------- #
class Speaker:
    """Thin, thread-safe wrapper around pyttsx3.

    Speech runs on a background thread so the GUI stays responsive. Starting a
    new utterance stops any that is in progress. All methods are safe to call
    even when pyttsx3 is not installed (they simply do nothing).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._engine = None
        self._thread = None
        # User-adjustable settings, applied to each utterance. None means
        # "leave the engine default alone".
        self.rate = None
        self.voice_id = None
        self._voices_cache = None
        self._default_rate = 200
        self._default_voice = None

    @property
    def available(self):
        return pyttsx3 is not None

    @property
    def default_rate(self):
        self.voices()  # ensure the engine defaults have been probed
        return self._default_rate

    def voices(self):
        """Return [(voice_id, name), ...] for the installed voices (cached)."""
        if not self.available:
            return []
        if self._voices_cache is None:
            self._voices_cache = []
            try:
                engine = pyttsx3.init()
                self._voices_cache = [
                    (v.id, v.name) for v in engine.getProperty("voices")]
                self._default_rate = engine.getProperty("rate") or 200
                self._default_voice = engine.getProperty("voice")
                engine.stop()
            except Exception:  # pragma: no cover - driver issues
                pass
        return self._voices_cache

    def speak(self, text):
        """Speak *text* aloud. Returns True if speech was started."""
        if not self.available or not text:
            return False
        self.stop()
        self._thread = threading.Thread(
            target=self._run, args=(text,), daemon=True)
        self._thread.start()
        return True

    def _run(self, text):
        with self._lock:
            try:
                engine = pyttsx3.init()
                self._engine = engine
                if self.rate is not None:
                    engine.setProperty("rate", self.rate)
                if self.voice_id is not None:
                    engine.setProperty("voice", self.voice_id)
                engine.say(text)
                engine.runAndWait()
            except Exception:  # pragma: no cover - engine/driver issues
                pass
            finally:
                self._engine = None

    def stop(self):
        """Interrupt any speech that is currently playing."""
        engine = self._engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:  # pragma: no cover
                pass


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #
class BudgetDB:
    """Thin wrapper around the SQLite database."""

    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._seed_categories()

    def _create_schema(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_items (
                id       INTEGER PRIMARY KEY,
                category TEXT NOT NULL UNIQUE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_lines (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                store    TEXT    NOT NULL,
                price    REAL    NOT NULL,
                date     TEXT    NOT NULL,   -- ISO 'YYYY-MM-DD'
                category INTEGER NOT NULL,
                FOREIGN KEY (category) REFERENCES budget_items(id) ON DELETE CASCADE
            )
            """
        )
        self.conn.commit()

    def _seed_categories(self):
        cur = self.conn.cursor()
        for cid, name in SEED_CATEGORIES:
            cur.execute(
                "INSERT OR IGNORE INTO budget_items (id, category) VALUES (?, ?)",
                (cid, name),
            )
        self.conn.commit()

    # -- categories --------------------------------------------------------- #
    def categories(self):
        """Return list of (id, category) ordered by name."""
        rows = self.conn.execute(
            "SELECT id, category FROM budget_items ORDER BY category"
        ).fetchall()
        return [(r["id"], r["category"]) for r in rows]

    # -- lines -------------------------------------------------------------- #
    def lines(self):
        """Return all budget lines joined with their category name."""
        return self.conn.execute(
            """
            SELECT l.id, l.store, l.price, l.date,
                   l.category AS category_id, i.category AS category_name
            FROM budget_lines l
            JOIN budget_items i ON i.id = l.category
            ORDER BY l.date DESC, l.id DESC
            """
        ).fetchall()

    def add_line(self, store, price, date, category_id):
        self.conn.execute(
            "INSERT INTO budget_lines (store, price, date, category) "
            "VALUES (?, ?, ?, ?)",
            (store, price, date, category_id),
        )
        self.conn.commit()

    def update_line(self, line_id, store, price, date, category_id):
        self.conn.execute(
            "UPDATE budget_lines SET store=?, price=?, date=?, category=? "
            "WHERE id=?",
            (store, price, date, category_id, line_id),
        )
        self.conn.commit()

    def delete_line(self, line_id):
        self.conn.execute("DELETE FROM budget_lines WHERE id=?", (line_id,))
        self.conn.commit()

    # -- aggregation for the chart ----------------------------------------- #
    def totals_by(self, group):
        """Return [(label, total_price), ...] grouped as requested.

        group is one of 'category', 'year', 'month'.
        """
        if group == "category":
            rows = self.conn.execute(
                """
                SELECT i.category AS label, COALESCE(SUM(l.price), 0) AS total
                FROM budget_lines l
                JOIN budget_items i ON i.id = l.category
                GROUP BY i.id
                ORDER BY total DESC
                """
            ).fetchall()
            return [(r["label"], r["total"]) for r in rows]

        if group == "year":
            rows = self.conn.execute(
                """
                SELECT strftime('%Y', date) AS label, SUM(price) AS total
                FROM budget_lines
                GROUP BY label
                ORDER BY label
                """
            ).fetchall()
            return [(r["label"], r["total"]) for r in rows]

        if group == "month":
            rows = self.conn.execute(
                """
                SELECT strftime('%m', date) AS mnum, SUM(price) AS total
                FROM budget_lines
                GROUP BY mnum
                """
            ).fetchall()
            by_month = {r["mnum"]: r["total"] for r in rows}
            # Show all 12 months in calendar order (0 where there's no spend).
            return [
                (MONTHS[i], by_month.get("{:02d}".format(i + 1), 0) or 0)
                for i in range(12)
            ]

        raise ValueError("unknown group: %r" % group)


# --------------------------------------------------------------------------- #
# Data tab
# --------------------------------------------------------------------------- #
class DataTab(ttk.Frame):
    """Add / edit / delete budget lines."""

    def __init__(self, master, db, on_change):
        super().__init__(master, padding=10)
        self.db = db
        self.on_change = on_change
        self.selected_id = None
        self._cat_by_name = {}

        self._build_form()
        self._build_table()
        self._bind_keys()
        self.refresh()

    def _build_form(self):
        form = ttk.LabelFrame(self, text="Budget line", padding=10)
        form.pack(fill="x")

        ttk.Label(form, text="Store").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.store_var = tk.StringVar()
        self.store_entry = ttk.Entry(form, textvariable=self.store_var, width=24)
        self.store_entry.grid(row=0, column=1, padx=4, pady=4)

        ttk.Label(form, text="Price (£)").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        self.price_var = tk.StringVar()
        self.price_entry = ttk.Entry(form, textvariable=self.price_var, width=12)
        self.price_entry.grid(row=0, column=3, padx=4, pady=4)

        ttk.Label(form, text="Date").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.date_var = tk.StringVar(value=dt.date.today().isoformat())
        self.date_entry = ttk.Entry(form, textvariable=self.date_var, width=24)
        self.date_entry.grid(row=1, column=1, padx=4, pady=4)
        ttk.Label(form, text="(YYYY-MM-DD)", foreground="#888").grid(
            row=1, column=1, sticky="e", padx=4)

        ttk.Label(form, text="Category").grid(row=1, column=2, sticky="w", padx=4, pady=4)
        self.category_var = tk.StringVar()
        self.category_cb = ttk.Combobox(
            form, textvariable=self.category_var, state="readonly", width=18)
        self.category_cb.grid(row=1, column=3, padx=4, pady=4)

        btns = ttk.Frame(form)
        btns.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.add_btn = ttk.Button(btns, text="Add (Ctrl+S)", command=self.add,
                                  underline=0)
        self.add_btn.pack(side="left", padx=(0, 6))
        self.update_btn = ttk.Button(
            btns, text="Update selected (Ctrl+S)", command=self.update,
            state="disabled")
        self.update_btn.pack(side="left", padx=6)
        self.delete_btn = ttk.Button(
            btns, text="Delete selected (Del)", command=self.delete,
            state="disabled")
        self.delete_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="Clear (Esc)", command=self.clear_form).pack(
            side="left", padx=6)

    def _build_table(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, pady=(10, 0))

        cols = ("id", "date", "store", "category", "price")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        headings = {
            "id": "ID", "date": "Date", "store": "Store",
            "category": "Category", "price": "Price",
        }
        widths = {"id": 50, "date": 100, "store": 200, "category": 160, "price": 110}
        for c in cols:
            self.tree.heading(c, text=headings[c])
            anchor = "e" if c == "price" else "w"
            self.tree.column(c, width=widths[c], anchor=anchor)
        self.tree.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        # Delete key removes the highlighted line; Enter loads it into the form.
        self.tree.bind("<Delete>", lambda _e: self.delete())
        self.tree.bind("<Return>", lambda _e: self.on_select())

    def _bind_keys(self):
        """Keyboard shortcuts scoped to the Data tab.

        Pressing Enter inside any form field adds or updates the line, so the
        whole flow can be driven without a mouse.
        """
        def _clear(_e):
            self.clear_form()
            return "break"  # don't fall through to the global Esc handler

        for entry in (self.store_entry, self.price_entry, self.date_entry):
            entry.bind("<Return>", lambda _e: self.save())
            entry.bind("<Escape>", _clear)
        # Enter on the category combobox behaves the same way.
        self.category_cb.bind("<Return>", lambda _e: self.save())

    # -- helpers ------------------------------------------------------------ #
    def refresh_categories(self):
        cats = self.db.categories()
        self._cat_by_name = {name: cid for cid, name in cats}
        names = [name for _, name in cats]
        self.category_cb["values"] = names
        if names and not self.category_var.get():
            self.category_var.set(names[0])

    def refresh(self):
        self.refresh_categories()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.db.lines():
            self.tree.insert(
                "", "end", iid=str(row["id"]),
                values=(row["id"], row["date"], row["store"],
                        row["category_name"], gbp(row["price"])),
            )

    def _read_form(self):
        store = self.store_var.get().strip()
        price_s = self.price_var.get().strip().lstrip("£").replace(",", "")
        date_s = self.date_var.get().strip()
        cat_name = self.category_var.get()

        if not store:
            raise ValueError("Please enter a store.")
        try:
            price = round(float(price_s), 2)
        except ValueError:
            raise ValueError("Price must be a number, e.g. 12.99")
        if price < 0:
            raise ValueError("Price cannot be negative.")
        try:
            dt.date.fromisoformat(date_s)
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format.")
        if cat_name not in self._cat_by_name:
            raise ValueError("Please choose a category.")
        return store, price, date_s, self._cat_by_name[cat_name]

    # -- actions ------------------------------------------------------------ #
    def save(self):
        """Update the selected line, or add a new one (Ctrl+S / Enter)."""
        if self.selected_id is None:
            self.add()
        else:
            self.update()

    def focus_new(self):
        """Clear the form and focus the first field, ready for a new line."""
        self.clear_form()
        self.store_entry.focus_set()

    def add(self):
        try:
            store, price, date_s, cat_id = self._read_form()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return
        self.db.add_line(store, price, date_s, cat_id)
        self.clear_form()
        self.refresh()
        self.on_change()

    def update(self):
        if self.selected_id is None:
            return
        try:
            store, price, date_s, cat_id = self._read_form()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return
        self.db.update_line(self.selected_id, store, price, date_s, cat_id)
        self.clear_form()
        self.refresh()
        self.on_change()

    def delete(self):
        if self.selected_id is None:
            return
        if not messagebox.askyesno("Delete", "Delete the selected budget line?"):
            return
        self.db.delete_line(self.selected_id)
        self.clear_form()
        self.refresh()
        self.on_change()

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected_id = int(sel[0])
        vals = self.tree.item(sel[0], "values")
        # vals = (id, date, store, category, price)
        self.date_var.set(vals[1])
        self.store_var.set(vals[2])
        self.category_var.set(vals[3])
        self.price_var.set(vals[4].lstrip("£").replace(",", ""))
        self.update_btn.config(state="normal")
        self.delete_btn.config(state="normal")

    def clear_form(self):
        self.selected_id = None
        if self.tree.selection():
            self.tree.selection_remove(self.tree.selection())
        self.store_var.set("")
        self.price_var.set("")
        self.date_var.set(dt.date.today().isoformat())
        self.refresh_categories()
        self.update_btn.config(state="disabled")
        self.delete_btn.config(state="disabled")


# --------------------------------------------------------------------------- #
# Chart tab
# --------------------------------------------------------------------------- #
class ChartTab(ttk.Frame):
    """Column graph of totals grouped by category / year / month."""

    GROUPS = [("Category", "category"), ("Year", "year"), ("Month", "month")]

    def __init__(self, master, db, speaker=None):
        super().__init__(master, padding=10)
        self.db = db
        self.speaker = speaker or Speaker()

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Group by:").pack(side="left")
        self.group_var = tk.StringVar(value="Category")
        cb = ttk.Combobox(
            top, textvariable=self.group_var, state="readonly",
            values=[label for label, _ in self.GROUPS], width=14)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda _e: self.draw())
        ttk.Button(top, text="Refresh (Ctrl+R)", command=self.draw,
                   underline=0).pack(side="left")

        self.speak_btn = ttk.Button(
            top, text="Read chart aloud (Ctrl+T)", command=self.speak_chart)
        self.speak_btn.pack(side="left", padx=(12, 0))
        self.stop_btn = ttk.Button(
            top, text="Stop reading (Esc)", command=self.stop_speaking)
        self.stop_btn.pack(side="left", padx=6)
        if not self.speaker.available:
            self.speak_btn.state(["disabled"])
            self.stop_btn.state(["disabled"])

        self._build_speech_settings()

        self.canvas = tk.Canvas(self, bg="white", highlightthickness=2,
                                highlightbackground="#ccc",
                                highlightcolor="#4a90d9", takefocus=True)
        self.canvas.pack(fill="both", expand=True, pady=(10, 0))
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        # The canvas can be focused with Tab; Enter or "r" reads it aloud so a
        # keyboard-only user never needs to reach for the button.
        self.canvas.bind("<Return>", lambda _e: self.speak_chart())
        self.canvas.bind("<r>", lambda _e: self.speak_chart())
        self.canvas.bind("<Escape>", lambda _e: self.stop_speaking())

        # A live text version of the chart: useful with a screen reader, and a
        # visible transcript of whatever is being read aloud.
        self.summary_var = tk.StringVar(
            value="Select a grouping and press Read chart aloud.")
        summary = ttk.Label(self, textvariable=self.summary_var,
                            wraplength=760, justify="left", foreground="#333")
        summary.pack(fill="x", pady=(8, 0))

    def _build_speech_settings(self):
        """Voice picker and speaking-rate slider for the read-aloud feature."""
        frame = ttk.Frame(self)
        frame.pack(fill="x", pady=(6, 0))

        voices = self.speaker.voices()
        self._voice_by_name = {name: vid for vid, name in voices}

        ttk.Label(frame, text="Voice:").pack(side="left")
        self.voice_var = tk.StringVar()
        self.voice_cb = ttk.Combobox(
            frame, textvariable=self.voice_var, state="readonly",
            width=30, values=[name for _, name in voices])
        self.voice_cb.pack(side="left", padx=(4, 16))
        self.voice_cb.bind("<<ComboboxSelected>>", self._on_voice)

        ttk.Label(frame, text="Speed:").pack(side="left")
        default_rate = self.speaker.default_rate
        self.rate_scale = ttk.Scale(
            frame, from_=80, to=320, orient="horizontal", length=180,
            command=self._on_rate)
        self.rate_scale.pack(side="left", padx=4)
        self.rate_label = ttk.Label(frame, width=9)
        self.rate_label.pack(side="left")

        # Create the label first: Scale.set() fires _on_rate, which needs it.
        self.rate_scale.set(default_rate)
        # Apply defaults up front so the very first utterance honours them.
        self.speaker.rate = int(default_rate)
        self._update_rate_label(default_rate)

        # Preselect the engine's current voice if we can identify it.
        name_by_id = {vid: name for vid, name in voices}
        current = name_by_id.get(self.speaker._default_voice)
        if current:
            self.voice_var.set(current)
            self.speaker.voice_id = self.speaker._default_voice
        elif voices:
            self.voice_var.set(voices[0][1])
            self.speaker.voice_id = voices[0][0]

        if not self.speaker.available:
            self.voice_cb.state(["disabled"])
            self.rate_scale.state(["disabled"])

    def _on_voice(self, _event=None):
        self.speaker.voice_id = self._voice_by_name.get(self.voice_var.get())

    def _on_rate(self, value):
        rate = int(float(value))
        self.speaker.rate = rate
        self._update_rate_label(rate)

    def _update_rate_label(self, rate):
        self.rate_label.config(text="{} wpm".format(int(float(rate))))

    def _group_key(self):
        label = self.group_var.get()
        return dict(self.GROUPS)[label]

    # -- accessibility: read the chart aloud -------------------------------- #
    def summary_text(self):
        """Build a spoken-language description of the current chart."""
        group_label = self.group_var.get().lower()
        data = self.db.totals_by(self._group_key())
        nonzero = [(label, val) for label, val in data if val and val > 0]

        if not nonzero:
            return ("Chart of total spend by {}. "
                    "There is no data to display yet.".format(group_label))

        total = sum(val for _, val in nonzero)
        ordered = sorted(nonzero, key=lambda t: t[1], reverse=True)
        top_label, top_val = ordered[0]

        parts = [
            "Total spend by {}.".format(group_label),
            "There {} {} {} with spending, totalling {}.".format(
                "is" if len(nonzero) == 1 else "are",
                len(nonzero),
                "entry" if len(nonzero) == 1 else "entries",
                spoken_gbp(total)),
            "The highest is {} at {}, {} percent of the total.".format(
                top_label, spoken_gbp(top_val),
                int(round(top_val / total * 100))),
        ]
        # Read every bar in the order it appears on screen.
        for label, val in nonzero:
            parts.append("{}: {}, {} percent.".format(
                label, spoken_gbp(val), int(round(val / total * 100))))
        return " ".join(parts)

    def speak_chart(self):
        """Announce the chart via text-to-speech and update the transcript."""
        text = self.summary_text()
        self.summary_var.set(text)
        if not self.speaker.available:
            self.summary_var.set(
                text + "\n\n(Install the 'pyttsx3' package to hear this "
                "read aloud: pip install pyttsx3)")
            return
        self.speaker.speak(text)

    def stop_speaking(self):
        self.speaker.stop()

    def draw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50 or h < 50:
            return

        data = self.db.totals_by(self._group_key())
        margin_left, margin_right = 90, 20
        margin_top, margin_bottom = 30, 60
        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom
        x0, y0 = margin_left, margin_top + plot_h  # bottom-left of plot area

        title = "Total spend by " + self.group_var.get().lower()
        c.create_text(w / 2, 15, text=title, font=("Helvetica", 13, "bold"))

        if not data or all(v <= 0 for _, v in data):
            c.create_text(w / 2, h / 2, text="No data to display",
                          fill="#888", font=("Helvetica", 12))
            return

        max_val = max(v for _, v in data)
        nice_max, step = self._nice_axis(max_val)

        # Y axis grid lines + GBP labels.
        n_ticks = int(round(nice_max / step)) if step else 1
        for i in range(n_ticks + 1):
            val = step * i
            y = y0 - (val / nice_max) * plot_h
            c.create_line(margin_left, y, w - margin_right, y, fill="#eee")
            c.create_text(margin_left - 8, y, text=gbp(val), anchor="e",
                          font=("Helvetica", 9))

        # Axes.
        c.create_line(x0, margin_top, x0, y0, fill="#333")
        c.create_line(x0, y0, w - margin_right, y0, fill="#333")

        # Bars.
        n = len(data)
        slot = plot_w / n
        bar_w = slot * 0.6
        for i, (label, val) in enumerate(data):
            cx = x0 + slot * i + slot / 2
            bar_h = (val / nice_max) * plot_h if nice_max else 0
            left = cx - bar_w / 2
            right = cx + bar_w / 2
            top = y0 - bar_h
            if val > 0:
                c.create_rectangle(left, top, right, y0,
                                   fill="#4a90d9", outline="#2f6da8")
                c.create_text(cx, top - 8, text=gbp(val),
                              font=("Helvetica", 8), fill="#333")
            # X label (rotated for readability when crowded).
            anchor = "n"
            if n > 8 or any(len(l) > 6 for l, _ in data):
                c.create_text(cx, y0 + 6, text=label, anchor="ne",
                              angle=35, font=("Helvetica", 8))
            else:
                c.create_text(cx, y0 + 6, text=label, anchor=anchor,
                              font=("Helvetica", 9))

    @staticmethod
    def _nice_axis(max_val):
        """Return (nice_max, step) giving a clean rounded Y axis."""
        if max_val <= 0:
            return 1.0, 1.0
        import math
        # Aim for ~5 ticks.
        raw_step = max_val / 5.0
        magnitude = 10 ** math.floor(math.log10(raw_step))
        for mult in (1, 2, 2.5, 5, 10):
            step = mult * magnitude
            if raw_step <= step:
                break
        nice_max = math.ceil(max_val / step) * step
        return nice_max, step


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
class BudgetApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Budget Tracker")
        self.geometry("820x600")
        self.minsize(680, 480)

        self.db = BudgetDB()
        self.speaker = Speaker()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.chart_tab = ChartTab(self.nb, self.db, speaker=self.speaker)
        self.data_tab = DataTab(self.nb, self.db, on_change=self.chart_tab.draw)

        # `underline` gives each tab a mnemonic (Alt+D / Alt+C); enable_traversal
        # activates those plus Ctrl+Tab / Ctrl+Shift+Tab to cycle tabs.
        self.nb.add(self.data_tab, text="Data", underline=0)
        self.nb.add(self.chart_tab, text="Chart", underline=0)
        self.nb.enable_traversal()

        self._build_menu()
        self._bind_shortcuts()

    # -- menu & shortcuts --------------------------------------------------- #
    def _build_menu(self):
        menubar = tk.Menu(self)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Quit", accelerator="Ctrl+Q",
                             command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu, underline=0)

        editmenu = tk.Menu(menubar, tearoff=0)
        editmenu.add_command(label="New line", accelerator="Ctrl+N",
                             command=self._new_line)
        editmenu.add_command(label="Save line", accelerator="Ctrl+S",
                             command=self.data_tab.save)
        editmenu.add_command(label="Delete line", accelerator="Del",
                             command=self.data_tab.delete)
        menubar.add_cascade(label="Edit", menu=editmenu, underline=0)

        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(label="Data tab", accelerator="Ctrl+1",
                             command=lambda: self._select_tab(0))
        viewmenu.add_command(label="Chart tab", accelerator="Ctrl+2",
                             command=lambda: self._select_tab(1))
        viewmenu.add_command(label="Refresh chart", accelerator="Ctrl+R",
                             command=self.chart_tab.draw)
        menubar.add_cascade(label="View", menu=viewmenu, underline=0)

        accmenu = tk.Menu(menubar, tearoff=0)
        state = "normal" if self.speaker.available else "disabled"
        accmenu.add_command(label="Read chart aloud", accelerator="Ctrl+T",
                            command=self._read_chart, state=state)
        accmenu.add_command(label="Stop reading", accelerator="Esc",
                            command=self.speaker.stop, state=state)
        menubar.add_cascade(label="Accessibility", menu=accmenu, underline=0)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="Keyboard shortcuts", accelerator="F1",
                             command=self._show_shortcuts)
        menubar.add_cascade(label="Help", menu=helpmenu, underline=0)

        self.config(menu=menubar)

    def _bind_shortcuts(self):
        # Bound on the toplevel with bind_all so they work whatever has focus.
        self.bind_all("<Control-q>", lambda _e: self.destroy())
        self.bind_all("<Control-n>", lambda _e: self._new_line())
        self.bind_all("<Control-s>", lambda _e: self.data_tab.save())
        self.bind_all("<Control-r>", lambda _e: self.chart_tab.draw())
        self.bind_all("<Control-t>", lambda _e: self._read_chart())
        self.bind_all("<Control-Key-1>", lambda _e: self._select_tab(0))
        self.bind_all("<Control-Key-2>", lambda _e: self._select_tab(1))
        self.bind_all("<Escape>", lambda _e: self.speaker.stop())
        self.bind_all("<F1>", lambda _e: self._show_shortcuts())

    def _select_tab(self, index):
        self.nb.select(index)
        return "break"

    def _new_line(self):
        self._select_tab(0)
        self.data_tab.focus_new()
        return "break"

    def _read_chart(self):
        """Switch to the chart, make sure it is current, then read it aloud."""
        self._select_tab(1)
        self.chart_tab.draw()
        self.chart_tab.speak_chart()
        return "break"

    def _show_shortcuts(self):
        messagebox.showinfo(
            "Keyboard shortcuts",
            "Navigation\n"
            "  Ctrl+1 / Alt+D   Data tab\n"
            "  Ctrl+2 / Alt+C   Chart tab\n"
            "  Ctrl+Tab         Next tab\n"
            "  Tab / Shift+Tab  Move between controls\n\n"
            "Editing (Data tab)\n"
            "  Ctrl+N           New line (clear form)\n"
            "  Ctrl+S / Enter   Add or update the line\n"
            "  Del              Delete the selected line\n"
            "  Esc              Clear the form\n\n"
            "Accessibility (Chart tab)\n"
            "  Ctrl+T           Read the chart aloud\n"
            "  Esc              Stop reading\n"
            "  Ctrl+R           Refresh the chart\n\n"
            "  F1               Show this help")


def main():
    app = BudgetApp()
    app.mainloop()


if __name__ == "__main__":
    main()
