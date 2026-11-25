import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser
import re

from config import (
    DEFAULT_LIMIT, SCROLL_ROUNDS, SCROLL_WAIT,
    DEFAULT_REVIEW_LOCATION,
)

from scraper.shopee import scrape_shopee
from scraper.tokopedia import scrape_tokopedia
from scraper.lazada import scrape_lazada
from scraper.news import scrape_news_indonesia
from scraper.google_reviews import scrape_google_reviews_by_name
from scraper.google_research import scrape_google_research

from storage import (
    init_db, save_rows_to_db,
    get_cached_rows, get_cached_rows_by_url, update_cache,
    default_ttl_hours, reviews_cache_keyword,
    add_scheduled_job, list_scheduled_jobs, update_scheduled_job,
    delete_scheduled_job, set_job_active, get_scheduled_job,
    finish_scheduled_job,
)
from scheduler import JobScheduler
from exporters import export_csv, export_json


MARKETS = ("Shopee", "Tokopedia", "Lazada", "Google Reviews", "News", "Google Research")

SCHEDULER_MARKETS = tuple(m for m in MARKETS if m != "Shopee")

SCHEMAS = {
    "Shopee": ["source", "keyword", "title", "harga", "rating", "comment", "url"],
    "Tokopedia": ["source","keyword","title","harga","rating", "url"],
    "Lazada": ["source", "keyword", "title", "harga", "rating", "sold", "url"],
    "Google Research": ["source", "keyword", "title", "authors", "year", "abstract", "url"],

    "Google Reviews": [
        "source", "keyword", "title", "category", "price_range", "review_count",
        "rating", "address", "country", "city", "url"
    ],

    "News": ["source", "keyword", "title", "published", "comment", "url"],
}

COL_WEIGHTS = {
    "source": 1.0,
    "keyword": 1.2,
    "title": 2.6,
    "harga": 1.0,
    "rating": 0.9,
    "review_count": 1.1,
    "sold" : 1.0,
    "category": 1.1,
    "price_range": 1.1,
    "address": 2.2,
    "country": 0.9,
    "city": 0.9,
    "published": 1.2,
    "comment": 2.2,
    "url": 2.6,
    "authors": 1.6,
    "year": 0.8,
    "abstract": 3.0,
}


def safe_get(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


def normalize_row(market: str, keyword: str, r: dict) -> dict:

    out = {
        "source": safe_get(r, "source", default=market),
        "keyword": keyword,

        "title": safe_get(r, "title"),
        "url": safe_get(r, "url"),
        "rating": safe_get(r, "rating"),
        "comment": safe_get(r, "comment"),
        "scraped_at": safe_get(r, "scraped_at"),

        "harga": safe_get(r, "harga", "price", "Price/Star", "price_text"),
        "price_text": safe_get(r, "price_text", "harga", "price", "Price/Star"),
        "price_num": safe_get(r, "price_num"),
        "sold_text": safe_get(r, "sold_text"),
        "sold_num": safe_get(r, "sold_num"),
        "sold": safe_get(r, "sold", "sold_text"),
        "shop_name": safe_get(r, "shop_name", "toko"),
        "location": safe_get(r, "location"),
        "image": safe_get(r, "image"),

        "category": safe_get(r, "category"),
        "price_range": safe_get(r, "price_range"),
        "review_count": safe_get(r, "review_count"),
        "address": safe_get(r, "address"),
        "country": safe_get(r, "country"),
        "city": safe_get(r, "city"),

        "authors": safe_get(r, "authors"),
        "year": safe_get(r, "year"),
        "abstract": safe_get(r, "abstract"),

        "published": safe_get(r, "published", "Price/Star"),
    }

    for col in SCHEMAS[market]:
        out.setdefault(col, "")

    return out


def row_for_storage(r: dict) -> dict:
    return {
        "source": _safe_str(r.get("source")),
        "keyword": _safe_str(r.get("keyword")),
        "title": _safe_str(r.get("title")),
        "harga": _safe_str(r.get("harga")),
        "rating": _safe_str(r.get("rating")),
        "comment": _safe_str(r.get("comment")),
        "url": _safe_str(r.get("url")),

        "authors": _safe_str(r.get("authors")),
        "year": _safe_str(r.get("year")),
        "abstract": _safe_str(r.get("abstract")),

        "category": _safe_str(r.get("category")),
        "price_range": _safe_str(r.get("price_range")),
        "review_count": _safe_str(r.get("review_count")),
        "address": _safe_str(r.get("address")),
        "country": _safe_str(r.get("country")),
        "city": _safe_str(r.get("city")),

        "published": _safe_str(r.get("published")),
        "scraped_at": _safe_str(r.get("scraped_at")),

        "price_text": _safe_str(r.get("price_text")),
        "price_num": _safe_str(r.get("price_num")),
        "sold_text": _safe_str(r.get("sold_text")),
        "sold_num": _safe_str(r.get("sold_num")),
        "sold": _safe_str(r.get("sold")),
        "shop_name": _safe_str(r.get("shop_name")),
        "location": _safe_str(r.get("location")),
        "image": _safe_str(r.get("image")),
    }


def _safe_str(x):
    return "" if x is None else str(x)


def _try_parse_number(s: str):
    s = _safe_str(s).strip()
    if not s:
        return None
    t = s.replace(" ", "")
    if "rp" in t.lower():
        return None
    if "–" in t or "-" in t:
        return None
    m = re.search(r"([0-9]+(?:[.,][0-9]+)?)", t)
    if not m:
        return None
    num = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(num)
    except Exception:
        return None


def _looks_like_http_url(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://")


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _evt=None):
        if self.tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                self.tip, text=self.text, justify="left",
                background="#0F172A", foreground="#E2E8F0",
                relief="solid", borderwidth=1, padx=8, pady=6,
                font=("Segoe UI", 9))
            label.pack()
        except Exception:
            pass

    def _hide(self, _evt=None):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


def _add_tooltip(widget, text):
    try:
        ToolTip(widget, text)
    except Exception:
        pass


class App:
    def __init__(self, master: tk.Tk):
        self.master = master
        master.title("Multi Source Scraper — E-commerce, Google Maps Reviews, Google Research, News")
        master.geometry("1200x820")
        master.minsize(820, 620)

        self.market = tk.StringVar(value=MARKETS[0])
        self.mode = tk.StringVar(value="keyword")
        self.headless = tk.BooleanVar(value=False)
        self.limit = tk.IntVar(value=DEFAULT_LIMIT)
        self.force_refresh = tk.BooleanVar(value=False)

        self.review_location = tk.StringVar(value=DEFAULT_REVIEW_LOCATION)
        self.scheduler = None
        self.sched_window = None
        self._sched_selected_id = None

        self.search_var = tk.StringVar(value="")

        self.rows_cache = []
        self.display_rows = []
        self.current_cols = []
        self.sort_state = {"col": None, "desc": False}

        self.running = False
        self.cancel_event = threading.Event()
        self.started_at = None
        self.timer_job = None

        self._rclick_row_id = None
        self._selected_url = ""

        self._build_style()
        self._build_layout()

        init_db()
        self._set_columns_for_market(self.market.get())
        self._on_market_change()
        self._set_status_idle()

        self.scheduler = JobScheduler(
            run_job=self._run_scheduled_job,
            is_busy=lambda: self.running,
            on_jobs_changed=lambda: self.master.after(
                0, self._refresh_scheduler_tree_if_open),
        )
        self.scheduler.start()
        try:
            self.master.protocol(
                "WM_DELETE_WINDOW", self._on_close)
        except Exception:
            pass

    def _on_close(self):
        if self.scheduler is not None:
            self.scheduler.stop()
        self.master.destroy()

    def _build_style(self):
        self.master.configure(background="#0F172A")
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = "#0F172A"
        panel = "#1E293B"
        panel2 = "#162032"
        fg = "#E2E8F0"
        muted = "#94A3B8"
        accent = "#22D3EE"
        accent_dark = "#0891B2"

        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg,
                        font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 14, "bold"),
                        foreground=fg)
        style.configure("Header.TLabel", font=("Segoe UI", 18, "bold"),
                        foreground="white")
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10),
                        foreground=muted)
        style.configure("Step.TLabel", font=("Segoe UI", 9, "bold"),
                        foreground=accent)
        style.configure("Small.TLabel", font=("Segoe UI", 9),
                        foreground=muted)
        style.configure("Status.TLabel", font=("Segoe UI", 10),
                        foreground=fg)
        style.configure("TButton", background=panel, foreground=fg,
                        font=("Segoe UI", 10), padding=(10, 6),
                        borderwidth=0)
        style.map("TButton",
                  background=[("active", "#334155"), ("disabled", "#1E293B")],
                  foreground=[("disabled", muted)])
        style.configure("Accent.TButton", background=accent_dark,
                        foreground="white", font=("Segoe UI", 10, "bold"),
                        padding=(14, 6))
        style.map("Accent.TButton",
                  background=[("active", accent)],
                  foreground=[("disabled", muted)])
        style.configure("TEntry", fieldbackground=panel, foreground=fg,
                        insertcolor=fg, padding=6)
        style.configure("TCombobox", fieldbackground=panel,
                        background=panel, foreground=fg, padding=6)
        style.configure("TSpinbox", fieldbackground=panel, foreground=fg,
                        background=panel, padding=6)
        style.configure("TCheckbutton", background=bg, foreground=fg,
                        font=("Segoe UI", 10))
        style.configure("TRadiobutton", background=bg, foreground=fg,
                        font=("Segoe UI", 10))
        style.configure("Treeview", background=bg, foreground=fg,
                        fieldbackground=bg, rowheight=30,
                        font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", background=panel,
                        foreground=accent, font=("Segoe UI", 10, "bold"),
                        padding=6)
        style.map("Treeview",
                  background=[("selected", "#155E75")],
                  foreground=[("selected", "white")])
        style.configure("Card.TFrame", background=panel2, padding=12)
        style.configure("CardTitle.TLabel", font=("Segoe UI", 11, "bold"),
                        background=panel2, foreground=fg)
        style.configure("Horizontal.TProgressbar", background=accent,
                        troughcolor=panel)

    def _build_layout(self):
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(4, weight=1)

        header = ttk.Frame(self.master, padding=(10, 10, 10, 2))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="◆  MARKET SCRAPER", style="Header.TLabel").grid(
            row=0, column=0, sticky="w")
        self.btn_schedule = ttk.Button(header, text="Jadwal",
                                       command=self._open_scheduler_window)
        self.btn_schedule.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.btn_help = ttk.Button(header, text="Cara Pakai",
                                   command=self._open_help_window)
        self.btn_help.grid(row=0, column=2, sticky="e", padx=(6, 0))
        ttk.Label(
            header,
            text="Scrape  •  Simpan ke database  •  Jadwalkan otomatis",
            style="Subtitle.TLabel").grid(row=1, column=0, columnspan=3,
                                          sticky="w")
        self.lbl_steps = ttk.Label(
            header,
            text="1  Pilih source   →   2  Isi keyword / URL   →   "
                 "3  Klik Scrape   →   4  Lihat & Export",
            style="Step.TLabel")
        self.lbl_steps.grid(row=2, column=0, columnspan=3, sticky="w")

        top = ttk.Frame(self.master, padding=10)
        top.grid(row=1, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        row1 = ttk.Frame(top)
        row1.grid(row=0, column=0, sticky="ew")
        row1.columnconfigure(6, weight=1)

        ttk.Label(row1, text="Source:").grid(row=0, column=0, sticky="w")
        self.cmb_market = ttk.Combobox(row1, values=MARKETS, textvariable=self.market, width=18, state="readonly")
        self.cmb_market.grid(row=0, column=1, sticky="w", padx=(6, 14))
        self.cmb_market.bind("<<ComboboxSelected>>", lambda e: self._on_market_change())

        ttk.Label(row1, text="Mode:").grid(row=0, column=2, sticky="e")
        self.rb_kw = ttk.Radiobutton(row1, text="Keyword", variable=self.mode, value="keyword")
        self.rb_url = ttk.Radiobutton(row1, text="URL", variable=self.mode, value="url")
        self.rb_kw.grid(row=0, column=3, sticky="w")
        self.rb_url.grid(row=0, column=4, sticky="w")

        ttk.Label(row1, text="Input:").grid(row=0, column=5, sticky="e", padx=(12, 6))
        self.entry = ttk.Entry(row1)
        self.entry.grid(row=0, column=6, sticky="ew")

        ttk.Label(row1, text="Limit:").grid(row=0, column=7, sticky="e", padx=(12, 6))
        self.spin = ttk.Spinbox(row1, from_=10, to=500, increment=10, textvariable=self.limit, width=8)
        self.spin.grid(row=0, column=8, sticky="w")

        row2 = ttk.Frame(top)
        row2.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.chk_headless = ttk.Checkbutton(row2, text="Headless", variable=self.headless)
        self.chk_headless.grid(row=0, column=0, sticky="w")

        ttk.Label(row2, text="Lokasi:").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.ent_location = ttk.Entry(row2, textvariable=self.review_location, width=16)
        self.ent_location.grid(row=0, column=2, sticky="w")

        self.chk_force = ttk.Checkbutton(row2, text="Paksa refresh", variable=self.force_refresh)
        self.chk_force.grid(row=0, column=3, sticky="w", padx=(12, 0))

        self.btn_scrape = ttk.Button(row2, text="▶  Scrape", command=self.on_scrape,
                                     style="Accent.TButton")
        self.btn_scrape.grid(row=0, column=4, padx=(16, 0))

        self.btn_stop = ttk.Button(row2, text="Stop", command=self.on_stop, state="disabled")
        self.btn_stop.grid(row=0, column=5, padx=(6, 0))

        self.btn_export_csv = ttk.Button(row2, text="Export CSV", command=self.on_export_csv, state="disabled")
        self.btn_export_csv.grid(row=0, column=5, padx=(12, 0))

        self.btn_export_json = ttk.Button(row2, text="Export JSON", command=self.on_export_json, state="disabled")
        self.btn_export_json.grid(row=0, column=6, padx=6)

        mid = ttk.Frame(self.master, padding=(10, 0, 10, 8))
        mid.grid(row=2, column=0, sticky="ew")
        mid.columnconfigure(1, weight=1)

        ttk.Label(mid, text="Search:").grid(row=0, column=0, sticky="w")
        self.entry_search = ttk.Entry(mid, textvariable=self.search_var)
        self.entry_search.grid(row=0, column=1, sticky="ew", padx=(6, 8))
        self.entry_search.bind("<KeyRelease>", lambda e: self._apply_filter())

        self.btn_reset_filter = ttk.Button(mid, text="Reset", command=self._reset_filter)
        self.btn_reset_filter.grid(row=0, column=2, sticky="w")

        card_border = tk.Frame(self.master, bd=1, relief="solid", background="#1E293B", highlightbackground="#334155", highlightthickness=1)
        card_border.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        card_border.columnconfigure(0, weight=1)

        self.card = ttk.Frame(card_border, style="Card.TFrame")
        self.card.grid(row=0, column=0, sticky="ew")
        self.card.columnconfigure(1, weight=1)

        self.lbl_icon = tk.Label(self.card, text="●", font=("Segoe UI", 14, "bold"),
                                 background="#162032", foreground="#94A3B8")
        self.lbl_icon.grid(row=0, column=0, sticky="w")

        self.lbl_card_title = ttk.Label(self.card, text="Ready", style="CardTitle.TLabel")
        self.lbl_card_title.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.lbl_card_meta = ttk.Label(self.card, text="", style="Small.TLabel")
        self.lbl_card_meta.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(2, 0))

        self.progress = ttk.Progressbar(self.card, mode="indeterminate", length=260)
        self.progress.grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 0))

        # MAIN
        main = ttk.Frame(self.master, padding=(10, 0, 10, 10))
        main.grid(row=4, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        title_bar = ttk.Frame(main)
        title_bar.grid(row=0, column=0, sticky="ew", pady=(6, 6))
        title_bar.columnconfigure(0, weight=1)

        ttk.Label(title_bar, text="Data Preview", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.lbl_meta = ttk.Label(title_bar, text="", style="Status.TLabel")
        self.lbl_meta.grid(row=0, column=1, sticky="e")

        table_frame = ttk.Frame(main)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, columns=(), show="headings", height=18)
        self.tree.grid(row=0, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("odd", background="#0F172A", foreground="#E2E8F0")
        self.tree.tag_configure("even", background="#1E293B", foreground="#E2E8F0")

        _add_tooltip(self.cmb_market, "Sumber data yang di-scrape:\nShopee, Tokopedia, Lazada,\nGoogle Reviews, Research, atau News.")
        _add_tooltip(self.entry, "Keyword untuk mode Keyword,\natau tempel URL lengkap untuk mode URL.")
        _add_tooltip(self.spin, "Jumlah maksimal baris yang diambil\nper sekali scrape (10–500).")
        _add_tooltip(self.chk_headless, "Headless = browser berjalan\ntanpa jendela. Matikan kalau perlu\nlogin/captcha manual (mis. Shopee).")
        _add_tooltip(self.ent_location, "Khusus Google Reviews:\nkota untuk filter lokasi. Kosong =\ntanpa filter lokasi.")
        _add_tooltip(self.chk_force, "Paksa refresh = abaikan cache\ndatabase dan scrape ulang ke web.")
        _add_tooltip(self.btn_scrape, "Mulai scrape. Data diambil dari\ndatabase dulu kalau masih segar,\nbaru ke web kalau belum ada.")
        _add_tooltip(self.btn_schedule, "Atur jadwal scrape otomatis:\nsumber, keyword, interval, aktif/nonaktif.")
        _add_tooltip(self.entry_search, "Filter baris yang sudah tampil\n(mencari di tabel, bukan scrape ulang).")

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_row)

        self._build_table_context_menu()
        self.tree.bind("<Button-3>", self._on_right_click_table)

        self.master.bind_all("<Control-c>", self._copy_selection)
        self.master.bind("<Configure>", self._on_resize)

        url_panel = ttk.Frame(main)
        url_panel.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        url_panel.columnconfigure(1, weight=1)

        ttk.Label(url_panel, text="URL:").grid(row=0, column=0, sticky="w")

        self.lbl_url = tk.Label(
            url_panel,
            text="(pilih satu row untuk lihat URL)",
            fg="#7DD3FC",
            background="#0F172A",
            cursor="hand2",
            underline=True,
            anchor="w",
            justify="left",
        )
        self.lbl_url.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        self.lbl_url.bind("<Button-1>", self._on_click_url_label)

        self._build_url_label_menu()
        self.lbl_url.bind("<Button-3>", self._on_right_click_url_label)

    def _build_table_context_menu(self):
        self.menu_table = tk.Menu(self.master, tearoff=0)
        self.menu_table.add_command(label="Open URL", command=self._menu_table_open_url)
        self.menu_table.add_command(label="Copy URL", command=self._menu_table_copy_url)
        self.menu_table.add_separator()
        self.menu_table.add_command(label="Copy row", command=self._menu_table_copy_row)

    def _build_url_label_menu(self):
        self.menu_url = tk.Menu(self.master, tearoff=0)
        self.menu_url.add_command(label="Open URL", command=self._menu_url_open)
        self.menu_url.add_command(label="Copy URL", command=self._menu_url_copy)

    def _on_market_change(self):
        market = self.market.get()
        self._set_columns_for_market(market)

        if market == "Google Reviews":
            self.ent_location.state(["!disabled"])
        else:
            self.ent_location.state(["disabled"])

        self._apply_filter()

    def _set_columns_for_market(self, market: str):
        cols = SCHEMAS.get(market, ["source", "title", "url"])
        self.current_cols = cols
        self.sort_state = {"col": None, "desc": False}

        self.tree.configure(columns=cols)
        for c in cols:
            self.tree.heading(c, text=c, command=lambda col=c: self._sort_by(col))
            self.tree.column(c, anchor="w", stretch=True, width=120)

        self._fit_columns()

    def _fit_columns(self):
        try:
            total_w = self.tree.winfo_width()
        except Exception:
            return
        if total_w < 200:
            return

        weights = [COL_WEIGHTS.get(c, 1.0) for c in self.current_cols]
        s = sum(weights) if weights else 1.0
        usable = max(200, total_w - 24)

        for c, w in zip(self.current_cols, weights):
            cw = int(usable * (w / s))
            cw = max(90, cw)
            self.tree.column(c, width=cw)

    def _on_resize(self, _evt):
        self._fit_columns()
        try:
            w = max(300, self.master.winfo_width() - 40)
            self.lbl_steps.config(wraplength=w)
        except Exception:
            pass

    def _set_status_idle(self):
        self.lbl_icon.config(text="●", foreground="#94A3B8")
        self.lbl_card_title.config(text="Ready")
        self.lbl_card_meta.config(text="Langkah 1–3 di atas, lalu klik Scrape.")

    def _set_status_running(self, market: str, headless: bool):
        self.lbl_icon.config(text="⏳", foreground="#22D3EE")
        self.lbl_card_title.config(text="Running…")
        mode = "Headless" if headless else "Visible"
        self.lbl_card_meta.config(text=f"Source: {market} | Mode: {mode} | Elapsed: 0s")

    def _set_status_success(self, market: str, rows_count: int, elapsed_s: int):
        self.lbl_icon.config(text="✔", foreground="#34D399")
        self.lbl_card_title.config(text="Completed")
        self.lbl_card_meta.config(text=f"Source: {market} | Data extracted: {rows_count} rows | Time: {elapsed_s}s")

    def _set_status_error(self, market: str, msg: str):
        self.lbl_icon.config(text="✖", foreground="#F87171")
        self.lbl_card_title.config(text="Failed")
        self.lbl_card_meta.config(text=f"Source: {market} | {msg}")

    def _set_status_cancel(self, market: str):
        self.lbl_icon.config(text="■", foreground="#FBBF24")
        self.lbl_card_title.config(text="Cancelled")
        self.lbl_card_meta.config(text=f"Source: {market} | Stop graceful berhasil (hasil tidak dimasukkan).")

    def set_busy(self, busy: bool):
        self.running = busy

        self.btn_scrape.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")

        has_data = bool(self.rows_cache)
        self.btn_export_csv.configure(state="normal" if (not busy and has_data) else "disabled")
        self.btn_export_json.configure(state="normal" if (not busy and has_data) else "disabled")

        st = "disabled" if busy else "normal"
        self.cmb_market.configure(state="disabled" if busy else "readonly")
        self.rb_kw.configure(state=st)
        self.rb_url.configure(state=st)
        self.entry.configure(state=st)
        self.spin.configure(state=st)
        self.chk_headless.configure(state=st)
        self.chk_force.configure(state=st)

        if self.market.get() == "Google Reviews":
            self.ent_location.configure(state=st)
        else:
            self.ent_location.configure(state="disabled")

        if busy:
            self.progress.start(12)
            self.master.configure(cursor="watch")
            self.started_at = time.time()
            self._start_timer()
        else:
            self.progress.stop()
            self.master.configure(cursor="")
            self._stop_timer()

    def _start_timer(self):
        self._stop_timer()

        def tick():
            if not self.running or self.started_at is None:
                return
            elapsed = int(time.time() - self.started_at)
            market = self.market.get()
            mode = "Headless" if self.headless.get() else "Visible"
            self.lbl_card_meta.config(text=f"Source: {market} | Mode: {mode} | Elapsed: {elapsed}s")
            self.timer_job = self.master.after(500, tick)

        tick()

    def _stop_timer(self):
        if self.timer_job is not None:
            try:
                self.master.after_cancel(self.timer_job)
            except Exception:
                pass
        self.timer_job = None
        self.started_at = None

    def _reset_filter(self):
        self.search_var.set("")
        self._apply_filter()

    def _apply_filter(self):
        q = (self.search_var.get() or "").strip().lower()

        if not q:
            self.display_rows = list(self.rows_cache)
        else:
            filtered = []
            for r in self.rows_cache:
                blob = " ".join(_safe_str(r.get(c, "")) for c in self.current_cols).lower()
                if q in blob:
                    filtered.append(r)
            self.display_rows = filtered

        if self.sort_state["col"]:
            self._sort_rows_inplace(self.sort_state["col"], self.sort_state["desc"])

        self._render_rows()

    def _render_rows(self):
        self.tree.delete(*self.tree.get_children())
        for idx, r in enumerate(self.display_rows):
            values = tuple(
                (_safe_str(r.get(c, "")).split("||")[0]
                 if c == "keyword" else r.get(c, ""))
                for c in self.current_cols)
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert("", "end", values=values, tags=(tag,))
        self._fit_columns()
        self.lbl_meta.config(text=f"Rows: {len(self.display_rows)} | Source: {self.market.get()}")

        self._selected_url = ""
        self.lbl_url.config(text="(pilih satu row untuk lihat URL)")

    def _sort_rows_inplace(self, col: str, desc: bool):
        def keyfn(r):
            v = _safe_str(r.get(col, ""))
            n = _try_parse_number(v)
            return (0, n) if n is not None else (1, v.lower())
        self.display_rows.sort(key=keyfn, reverse=desc)

    def _sort_by(self, col: str):
        if not self.display_rows:
            return
        if self.sort_state["col"] == col:
            self.sort_state["desc"] = not self.sort_state["desc"]
        else:
            self.sort_state["col"] = col
            self.sort_state["desc"] = False
        self._sort_rows_inplace(col, self.sort_state["desc"])
        self._render_rows()

    def _url_col_index(self):
        try:
            return self.current_cols.index("url")
        except ValueError:
            return None

    def _get_row_url_by_item(self, item_id: str) -> str:
        if not item_id:
            return ""
        vals = self.tree.item(item_id, "values") or ()
        idx = self._url_col_index()
        if idx is None or idx >= len(vals):
            return ""
        return _safe_str(vals[idx]).strip()

    def _copy_text(self, text: str):
        try:
            self.master.clipboard_clear()
            self.master.clipboard_append(text)
        except Exception:
            pass

    def _open_url(self, url: str):
        url = (url or "").strip()
        if not url:
            return
        try:
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Gagal buka URL", str(e))

    def _on_select_row(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            self._selected_url = ""
            self.lbl_url.config(text="(pilih satu row untuk lihat URL)")
            return
        row_id = sel[0]
        url = self._get_row_url_by_item(row_id)
        self._selected_url = url
        self.lbl_url.config(text=url if url else "(row ini tidak punya URL)")

    def _on_click_url_label(self, _evt=None):
        if self._selected_url:
            self._open_url(self._selected_url)

    def _on_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return
        try:
            col_index = int(col_id.replace("#", "")) - 1
            col_name = self.current_cols[col_index]
        except Exception:
            return
        if col_name != "url":
            return
        url = self._get_row_url_by_item(row_id)
        if url:
            self._open_url(url)

    def _copy_selection(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        lines = []
        lines.append("\t".join(self.current_cols))
        for item_id in sel:
            vals = self.tree.item(item_id, "values")
            lines.append("\t".join(_safe_str(v) for v in vals))
        self._copy_text("\n".join(lines))

    def _on_right_click_table(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            self._rclick_row_id = row_id
        else:
            self._rclick_row_id = None

        url = self._get_row_url_by_item(self._rclick_row_id) if self._rclick_row_id else ""
        state_url = "normal" if url else "disabled"
        state_row = "normal" if self._rclick_row_id else "disabled"

        self.menu_table.entryconfigure("Open URL", state=state_url)
        self.menu_table.entryconfigure("Copy URL", state=state_url)
        self.menu_table.entryconfigure("Copy row", state=state_row)

        try:
            self.menu_table.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu_table.grab_release()

    def _menu_table_open_url(self):
        url = self._get_row_url_by_item(self._rclick_row_id)
        self._open_url(url)

    def _menu_table_copy_url(self):
        url = self._get_row_url_by_item(self._rclick_row_id)
        if url:
            self._copy_text(url)

    def _menu_table_copy_row(self):
        if not self._rclick_row_id:
            return
        vals = self.tree.item(self._rclick_row_id, "values") or ()
        self._copy_text("\t".join(_safe_str(v) for v in vals))

    def _on_right_click_url_label(self, event):
        url = self._selected_url or ""
        st = "normal" if url else "disabled"
        self.menu_url.entryconfigure("Open URL", state=st)
        self.menu_url.entryconfigure("Copy URL", state=st)

        try:
            self.menu_url.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu_url.grab_release()

    def _menu_url_open(self):
        if self._selected_url:
            self._open_url(self._selected_url)

    def _menu_url_copy(self):
        if self._selected_url:
            self._copy_text(self._selected_url)

    def on_stop(self):
        if not self.running:
            return
        self.cancel_event.set()
        self.lbl_icon.config(text="■")
        self.lbl_card_title.config(text="Stopping…")
        self.lbl_card_meta.config(text="Stop requested… akan berhenti setelah proses saat ini selesai.")

    def _scrape_from_web(self, market, mode, text, headless, limit,
                         location="", on_progress=None, on_partial=None):
        if market == "Shopee":
            return scrape_shopee(
                keyword=text if mode == "keyword" else None,
                url=text if mode == "url" else None,
                headless=headless, limit=limit,
                scroll_rounds=SCROLL_ROUNDS, wait=SCROLL_WAIT)
        if market == "Tokopedia":
            return scrape_tokopedia(
                keyword=text if mode == "keyword" else None,
                url=text if mode == "url" else None,
                headless=headless, limit=limit,
                scroll_rounds=SCROLL_ROUNDS, wait=SCROLL_WAIT,
                on_progress=on_progress, on_partial=on_partial)
        if market == "Lazada":
            return scrape_lazada(
                keyword=text if mode == "keyword" else None,
                url=text if mode == "url" else None,
                headless=headless, limit=limit,
                scroll_rounds=SCROLL_ROUNDS, wait=SCROLL_WAIT)
        if market == "Google Reviews":
            if mode == "url":
                raise ValueError(
                    "Google Reviews tidak mendukung mode URL.")
            loc = (location or "").strip()
            return scrape_google_reviews_by_name(
                place_name=text, headless=headless, limit=limit,
                scroll_rounds=SCROLL_ROUNDS, wait=SCROLL_WAIT,
                location=loc)
        if market == "Google Research":
            return scrape_google_research(
                keyword=text if mode == "keyword" else None,
                url=text if mode == "url" else None,
                limit=limit, wait=0.2)
        if market == "News":
            return scrape_news_indonesia(
                keyword=text if mode == "keyword" else None,
                url=text if mode == "url" else None, limit=limit)
        raise ValueError("Source tidak dikenali")

    def _run_scrape_pipeline(self, market, mode, text, headless, limit,
                             location="", force_refresh=False,
                             on_progress=None, on_partial=None):
        cache_keyword = text
        if market == "Google Reviews" and mode == "keyword":
            cache_keyword = reviews_cache_keyword(text, location)
        cached_rows = []
        if not force_refresh:
            if mode == "url":
                cached, fresh = get_cached_rows_by_url(
                    text, ttl_hours=default_ttl_hours(market))
            else:
                cached, fresh = get_cached_rows(market, cache_keyword)
            if fresh and cached:
                cached_rows = [normalize_row(market, cache_keyword, r)
                              for r in cached]
                if len(cached_rows) >= limit:
                    return cached_rows[:limit], "database"
        try:
            raw = self._scrape_from_web(
                market, mode, text, headless, limit, location,
                on_progress=on_progress, on_partial=on_partial)
        except Exception:
            if cached_rows:
                return cached_rows, "database"
            raise
        rows = [normalize_row(market, cache_keyword, r) for r in (raw or [])]
        clean_rows = []
        for r in rows:
            if not r.get("url"):
                continue
            clean_rows.append(row_for_storage(r))
        if clean_rows:
            save_rows_to_db(clean_rows)
        if cached_rows:
            cached_urls = {(r.get("url") or "").strip().lower()
                           for r in cached_rows}
            new_rows = [r for r in rows
                        if (r.get("url") or "").strip().lower()
                        not in cached_urls]
            merged = cached_rows + new_rows[:limit - len(cached_rows)]
            update_cache(market, cache_keyword, row_count=len(merged))
            return merged, "web"
        if clean_rows:
            update_cache(market, cache_keyword, row_count=len(clean_rows))
        return rows, "web"

    def _run_scheduled_job(self, job):
        market = job.get("source", "")
        if market == "Shopee":
            return 0, "Shopee dikecualikan dari scheduler"
        try:
            rows, _src = self._run_scrape_pipeline(
                market, job.get("mode", "keyword"),
                job.get("keyword", ""), headless=True,
                limit=int(job.get("limit_rows") or DEFAULT_LIMIT),
                location=DEFAULT_REVIEW_LOCATION, force_refresh=True)
            return len(rows), ""
        except Exception as e:
            return 0, str(e)

    def on_scrape(self):
        text = self.entry.get().strip()
        if not text:
            messagebox.showwarning("Input kosong", "Masukkan keyword / URL / nama tempat.")
            return

        market = self.market.get()
        mode = self.mode.get()
        headless = self.headless.get()
        limit = int(self.limit.get())
        force_refresh = self.force_refresh.get()
        location = self.review_location.get().strip()

        if self.scheduler is not None and self.scheduler.current_job_id is not None:
            messagebox.showwarning(
                "Scheduler sedang jalan",
                "Scheduler sedang menjalankan job terjadwal. "
                "Tunggu sebentar lalu coba lagi.")
            return

        if mode == "url":
            if market == "Google Reviews":
                messagebox.showwarning("Mode tidak didukung", "Google Reviews tidak menggunakan mode URL.")
                return
            if not _looks_like_http_url(text):
                messagebox.showwarning("URL tidak valid", "Mode URL harus diawali http:// atau https://")
                return

        self.cancel_event.clear()
        self._set_columns_for_market(market)
        self._set_status_running(market, headless)
        self.set_busy(True)

        def worker():
            try:
                partial_note = {"text": ""}

                def _progress(found, limit_, round_no, snapshot=None):
                    self.master.after(
                        0, lambda: self.lbl_card_meta.config(
                            text=f"Source: {market} | Mengumpulkan "
                                 f"{found}/{limit_}… • ronde {round_no}"))

                def _partial(error, found):
                    partial_note["text"] = f"parsial ({found} baris) — {error}"

                rows, data_source = self._run_scrape_pipeline(
                    market, mode, text, headless, limit, location,
                    force_refresh=force_refresh,
                    on_progress=_progress, on_partial=_partial)

                if self.cancel_event.is_set():
                    self.master.after(0, lambda: self._finish_cancelled(market))
                    return

                def on_done():
                    self.rows_cache = rows
                    self.display_rows = list(rows)
                    self._apply_filter()

                    elapsed = 0
                    if self.started_at:
                        elapsed = int(time.time() - self.started_at)

                    self._set_status_success(market, len(rows), elapsed)
                    label = "database (cache)" if data_source == "database" else "web"
                    suffix = f" | Data: {label}"
                    if partial_note["text"]:
                        suffix += f" | Selesai {partial_note['text']}"
                    shortfall = len(rows) < limit
                    if shortfall and data_source == "database":
                        suffix += (
                            f" | ⚠ Hanya {len(rows)}/{limit} dari cache"
                            " — Paksa refresh untuk scrape ulang")
                    elif shortfall:
                        suffix += (
                            f" | ⚠ Hanya {len(rows)}/{limit}"
                            " — scrape berhenti, feed tidak "
                            "bertambah lagi")
                    self.lbl_card_meta.config(
                        text=self.lbl_card_meta.cget("text") + suffix)
                    self.set_busy(False)
                    if shortfall and data_source != "database":
                        messagebox.showwarning(
                            "Hasil kurang dari limit",
                            f"Hanya terkumpul {len(rows)} dari {limit} "
                            "baris yang diminta.\n\nScrape berhenti "
                            "sebelum limit tercapai: feed tidak "
                            "bertambah lagi atau batas scroll sudah "
                            "habis. Coba Paksa refresh untuk mencoba "
                            "lagi.")

                self.master.after(0, on_done)

            except Exception as err:
                msg = str(err)

                def on_err():
                    self.rows_cache = []
                    self.display_rows = []
                    self._apply_filter()
                    self._set_status_error(market, msg)
                    self.set_busy(False)
                    messagebox.showerror("Error", msg)

                self.master.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_cancelled(self, market: str):
        self._set_status_cancel(market)
        self.set_busy(False)

    def _open_help_window(self):
        win = tk.Toplevel(self.master)
        win.title("Cara Pakai — Market Scraper")
        win.geometry("620x480")
        win.configure(background="#0F172A")
        text = tk.Text(win, wrap="word", background="#1E293B",
                       foreground="#E2E8F0", font=("Segoe UI", 10),
                       padx=14, pady=14, borderwidth=0)
        text.pack(fill="both", expand=True)
        text.insert("1.0", (
            "CARA PAKAI DALAM 4 LANGKAH\n"
            "============================\n\n"
            "1. Pilih Source — Shopee, Tokopedia, Lazada,\n"
            "   Google Reviews, Google Research, atau News.\n\n"
            "2. Pilih Mode & isi Input — Keyword (mis. \"mouse\")\n"
            "   atau URL lengkap kalau Mode = URL.\n"
            "   Atur Limit (jumlah baris maksimal).\n\n"
            "3. Klik Scrape — tunggu sampai status berubah\n"
            "   menjadi Completed. Tombol Stop membatalkan\n"
            "   scrape yang sedang berjalan.\n\n"
            "4. Lihat & Export — hasil tampil di tabel bawah.\n"
            "   Gunakan Search untuk menyaring tabel,\n"
            "   klik kanan baris untuk Copy URL / Open URL,\n"
            "   lalu Export CSV atau Export JSON.\n\n"
            "CACHE-FIRST (DATABASE DULU)\n"
            "===========================\n"
            "Scrape pertama mengambil dari web, lalu disimpan\n"
            "ke database. Scrape berikutnya dengan keyword\n"
            "yang sama mengambil dari database dulu kalau\n"
            "masih segar (label \"Data: database (cache)\").\n"
            "Centang \"Paksa refresh\" kalau ingin scrape\n"
            "ulang ke web dan mengabaikan cache.\n\n"
            "JADWAL OTOMATIS\n"
            "===============\n"
            "Klik Jadwal, lalu tambah job: pilih source,\n"
            "keyword/URL, limit, dan interval (menit/jam/hari).\n"
            "Job aktif berjalan sendiri selama app dibuka.\n"
            "Shopee dikecualikan dari scheduler.\n\n"
            "TIPS\n"
            "====\n"
            "• Arahkan kursor ke tombol/kontrol untuk melihat\n"
            "  penjelasan singkatnya (tooltip).\n"
            "• Shopee memakai mode Visible agar bisa login /\n"
            "  captcha manual bila diperlukan.\n"
            "• Kalau hasil 0 baris, cek koneksi dan coba\n"
            "  Paksa refresh, atau kecilkan Limit.\n"
        ))
        text.config(state="disabled")
        ttk.Button(win, text="Tutup", command=win.destroy).pack(pady=(6, 10))

    def _refresh_scheduler_tree_if_open(self):
        if self.sched_window is not None:
            try:
                if self.sched_window.winfo_exists():
                    self._refresh_scheduler_tree()
            except Exception:
                pass

    def _refresh_scheduler_tree(self):
        if not hasattr(self, "sched_tree"):
            return
        self.sched_tree.delete(*self.sched_tree.get_children())
        for j in list_scheduled_jobs():
            interval = j.get("interval_minutes", 0)
            if interval % 1440 == 0 and interval >= 1440:
                interval_txt = f"{interval // 1440} hari"
            elif interval % 60 == 0:
                interval_txt = f"{interval // 60} jam"
            else:
                interval_txt = f"{interval} menit"
            self.sched_tree.insert("", "end", values=(
                j.get("id", ""), j.get("source", ""), j.get("keyword", ""),
                j.get("mode", ""), interval_txt,
                j.get("next_run_at", "") or "-",
                j.get("last_run_at", "") or "-",
                j.get("last_status", "") or "-",
                j.get("last_rows", "") if j.get("last_rows") is not None else "-",
                "Aktif" if j.get("active") else "Nonaktif",
            ))

    def _open_scheduler_window(self):
        if self.sched_window is not None:
            try:
                if self.sched_window.winfo_exists():
                    self.sched_window.lift()
                    self._refresh_scheduler_tree()
                    return
            except Exception:
                pass
        win = tk.Toplevel(self.master)
        win.title("Jadwal Otomatis")
        win.geometry("980x520")
        self.sched_window = win
        self._sched_selected_id = None

        form = ttk.Frame(win, padding=10)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="Source:").grid(row=0, column=0, sticky="w")
        self.sched_market = tk.StringVar(value=SCHEDULER_MARKETS[0])
        ttk.Combobox(form, values=SCHEDULER_MARKETS,
                     textvariable=self.sched_market, width=18,
                     state="readonly").grid(row=0, column=1, sticky="w", padx=(6, 12))

        ttk.Label(form, text="Mode:").grid(row=0, column=2, sticky="e")
        self.sched_mode = tk.StringVar(value="keyword")
        ttk.Radiobutton(form, text="Keyword", variable=self.sched_mode,
                        value="keyword").grid(row=0, column=3, sticky="w")
        ttk.Radiobutton(form, text="URL", variable=self.sched_mode,
                        value="url").grid(row=0, column=4, sticky="w")

        ttk.Label(form, text="Input:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.sched_entry = ttk.Entry(form, width=50)
        self.sched_entry.grid(row=1, column=1, columnspan=3, sticky="ew",
                              padx=(6, 0), pady=(8, 0))

        ttk.Label(form, text="Limit:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.sched_limit = tk.IntVar(value=DEFAULT_LIMIT)
        ttk.Spinbox(form, from_=10, to=500, increment=10,
                    textvariable=self.sched_limit, width=8).grid(
                        row=2, column=1, sticky="w", padx=(6, 0), pady=(8, 0))

        ttk.Label(form, text="Interval:").grid(row=2, column=2, sticky="e", pady=(8, 0))
        self.sched_interval_val = tk.StringVar(value="24")
        ttk.Entry(form, textvariable=self.sched_interval_val, width=8).grid(
            row=2, column=3, sticky="w", padx=(6, 0), pady=(8, 0))
        self.sched_interval_unit = tk.StringVar(value="jam")
        ttk.Combobox(form, values=("menit", "jam", "hari"),
                     textvariable=self.sched_interval_unit, width=8,
                     state="readonly").grid(row=2, column=4, sticky="w", padx=(6, 0), pady=(8, 0))

        self.sched_active = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Aktif", variable=self.sched_active).grid(
            row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Label(form, text="Google Reviews terjadwal memakai lokasi default "
                  "config (kosong = tanpa filter). "
                  "Scheduler hanya jalan selama app dibuka.",
                  style="Small.TLabel").grid(row=3, column=2, columnspan=3,
                                             sticky="w", pady=(8, 0))

        btns = ttk.Frame(win, padding=(10, 0, 10, 8))
        btns.grid(row=1, column=0, sticky="ew")
        ttk.Button(btns, text="Simpan Job",
                   command=self._scheduler_save).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Hapus",
                   command=self._scheduler_delete).grid(row=0, column=1, padx=6)
        ttk.Button(btns, text="Aktif/Nonaktif",
                   command=self._scheduler_toggle).grid(row=0, column=2, padx=6)
        ttk.Button(btns, text="Jalankan Sekarang",
                   command=self._scheduler_run_now).grid(row=0, column=3, padx=6)
        ttk.Button(btns, text="Tutup",
                   command=win.destroy).grid(row=0, column=4, padx=6)

        cols = ("id", "source", "keyword", "mode", "interval", "next_run",
                "last_run", "status", "rows", "aktif")
        self.sched_tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        for c in cols:
            self.sched_tree.heading(c, text=c)
            self.sched_tree.column(c, width=90, anchor="w")
        self.sched_tree.column("keyword", width=180)
        self.sched_tree.column("next_run", width=150)
        self.sched_tree.column("last_run", width=150)
        self.sched_tree.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        win.rowconfigure(2, weight=1)
        win.columnconfigure(0, weight=1)
        self.sched_tree.bind("<<TreeviewSelect>>", self._scheduler_on_select)
        self._refresh_scheduler_tree()

    def _scheduler_interval_minutes(self):
        try:
            val = float(self.sched_interval_val.get())
        except Exception:
            raise ValueError("Interval harus angka.")
        unit = self.sched_interval_unit.get()
        minutes = val * (1 if unit == "menit" else 60 if unit == "jam" else 1440)
        if minutes < 1:
            raise ValueError("Interval minimal 1 menit.")
        return int(minutes)

    def _scheduler_on_select(self, _evt=None):
        sel = self.sched_tree.selection()
        if not sel:
            return
        vals = self.sched_tree.item(sel[0], "values")
        if not vals:
            return
        job = get_scheduled_job(int(vals[0]))
        if not job:
            return
        self._sched_selected_id = job["id"]
        self.sched_market.set(job["source"])
        self.sched_mode.set(job["mode"])
        self.sched_entry.delete(0, tk.END)
        self.sched_entry.insert(0, job["keyword"])
        self.sched_limit.set(job["limit_rows"])
        interval = int(job["interval_minutes"])
        if interval % 1440 == 0:
            self.sched_interval_val.set(str(interval // 1440))
            self.sched_interval_unit.set("hari")
        elif interval % 60 == 0:
            self.sched_interval_val.set(str(interval // 60))
            self.sched_interval_unit.set("jam")
        else:
            self.sched_interval_val.set(str(interval))
            self.sched_interval_unit.set("menit")
        self.sched_active.set(bool(job["active"]))

    def _scheduler_save(self):
        try:
            keyword = self.sched_entry.get().strip()
            if not keyword:
                messagebox.showwarning("Input kosong", "Isi keyword / URL job.")
                return
            if self.sched_mode.get() == "url" and not _looks_like_http_url(keyword):
                messagebox.showwarning("URL tidak valid", "Mode URL harus diawali http:// atau https://")
                return
            interval = self._scheduler_interval_minutes()
            import datetime as _dt
            next_run = (_dt.datetime.now() + _dt.timedelta(minutes=interval)).isoformat(timespec="seconds")
            if self._sched_selected_id:
                update_scheduled_job(
                    self._sched_selected_id,
                    source=self.sched_market.get(), keyword=keyword,
                    mode=self.sched_mode.get(),
                    limit_rows=int(self.sched_limit.get()),
                    interval_minutes=interval, next_run_at=next_run,
                    active=1 if self.sched_active.get() else 0)
            else:
                add_scheduled_job(
                    self.sched_market.get(), keyword,
                    mode=self.sched_mode.get(),
                    limit_rows=int(self.sched_limit.get()),
                    interval_minutes=interval, next_run_at=next_run)
            self._refresh_scheduler_tree()
        except Exception as e:
            messagebox.showerror("Gagal simpan job", str(e))

    def _scheduler_delete(self):
        if not self._sched_selected_id:
            messagebox.showinfo("Pilih job", "Pilih dulu job yang mau dihapus.")
            return
        delete_scheduled_job(self._sched_selected_id)
        self._sched_selected_id = None
        self._refresh_scheduler_tree()

    def _scheduler_toggle(self):
        if not self._sched_selected_id:
            messagebox.showinfo("Pilih job", "Pilih dulu job yang mau diubah.")
            return
        job = get_scheduled_job(self._sched_selected_id)
        if job:
            set_job_active(job["id"], not bool(job["active"]))
            self._refresh_scheduler_tree()

    def _scheduler_run_now(self):
        if not self._sched_selected_id:
            messagebox.showinfo("Pilih job", "Pilih dulu job yang mau dijalankan.")
            return
        job = get_scheduled_job(self._sched_selected_id)
        if not job:
            return
        if self.running:
            messagebox.showwarning("Sedang sibuk", "Tunggu scrape manual selesai dulu.")
            return

        def worker():
            started = time.strftime("%Y-%m-%dT%H:%M:%S")
            rows_found, error = self._run_scheduled_job(job)
            finish_scheduled_job(
                job["id"], "done" if not error else "failed",
                rows_found=rows_found, error=error or "",
                started_at=started)
            self.master.after(0, self._refresh_scheduler_tree_if_open)

        threading.Thread(target=worker, daemon=True).start()

    def on_export_csv(self):
        if not self.rows_cache:
            messagebox.showinfo("Tidak ada data", "Belum ada data.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="data.csv"
        )
        if path:
            export_csv(path, self.rows_cache)
            messagebox.showinfo("Berhasil", f"CSV tersimpan di:\n{path}")

    def on_export_json(self):
        if not self.rows_cache:
            messagebox.showinfo("Tidak ada data", "Belum ada data.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="data.json"
        )
        if path:
            export_json(path, self.rows_cache)
            messagebox.showinfo("Berhasil", f"JSON tersimpan di:\n{path}")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()