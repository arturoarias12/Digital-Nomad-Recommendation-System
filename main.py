"""
main.py
Team: Blue Team
Members:
  - Arturo Arias (aaarias)
  - Madison Shen (mshen3)
  - Jiafu Wang (jiafuw)
  - Jiaqi Xu (jiaqix2)
  - Jiaming Zhu (jzhu7)

Purpose:
  Digital Nomad Recommendation System — Tkinter GUI application.
  Loads, filters, and visualizes destination recommendations via
  Table, Map, and Home dashboards; supports trip planning, saved plan
  comparison (Plan A vs Plan B), and has theme settings.
  Provides cache vs. fresh data modes.

This file is not imported by any other. It is the main entry point.

Imports:
  Local modules: dn_recommendations
  Standard library: tkinter, pathlib, json, os, re, math, datetime, typing
  Third-party: pandas, matplotlib
"""

import json
import re
import os
import math
import pandas as pd
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.image import imread
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

matplotlib.use("TkAgg")

# Engine API + custom exceptions (from dn_recommendations.py)
from dn_recommendations import (
    build_recommendations,
    fetch_visa_data,
    fetch_cost_of_living_data,
    fetch_internet_speed_data,
    CostOfLivingRateLimitError,
    CostOfLivingFetchError,
    set_cache_only_mode,
    NoCachedDataError,  
)

# =============================================================================
# Persistent Plan Store (JSON file on disk)
# =============================================================================

APP_DIR = os.getcwd()
PLANS_FILE = os.path.join(APP_DIR, "plans.json")


def _ensure_app_dir() -> None:
    """Create the app folder if it doesn't exist."""
    os.makedirs(APP_DIR, exist_ok=True)


def _read_plans_store() -> List[Dict[str, Any]]:
    """Load saved plans from disk; return an empty list on error/missing file."""
    _ensure_app_dir()
    if not os.path.exists(PLANS_FILE):
        return []
    try:
        with open(PLANS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_plans_store(plans: List[Dict[str, Any]]) -> None:
    """Atomic write of saved plans to disk."""
    _ensure_app_dir()
    tmp_path = PLANS_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(plans, f, indent=2)
    os.replace(tmp_path, PLANS_FILE)


def load_all_plans_from_store() -> List[Dict[str, Any]]:
    return _read_plans_store()


def save_plan_to_store(plan: Dict[str, Any]) -> None:
    plans = _read_plans_store()
    pid = plan.get("id")
    for i, p in enumerate(plans):
        if p.get("id") == pid:
            plans[i] = plan
            break
    else:
        plans.append(plan)
    _write_plans_store(plans)


def delete_plan_from_store(plan_id: str) -> None:
    plans = [p for p in _read_plans_store() if p.get("id") != plan_id]
    _write_plans_store(plans)


def rename_plan_in_store(plan_id: str, new_name: str) -> None:
    plans = _read_plans_store()
    for p in plans:
        if p.get("id") == plan_id:
            p["name"] = new_name
            break
    _write_plans_store(plans)


# =============================================================================
# Data classes for app state
# =============================================================================

@dataclass
class Plan:
    id: str
    name: str
    created_at: str
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppState:
    theme: str = "light"          # 'light', 'dark', 'blue'
    default_region: str = "Global"
    saved_plans: List[Plan] = field(default_factory=list)


# =============================================================================
# Small utilities
# =============================================================================

def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ask_save_path(default_name: str, defaultext: str = ".json") -> Optional[str]:
    return filedialog.asksaveasfilename(
        title="Save As",
        defaultextension=defaultext,
        filetypes=[("JSON", ".json"), ("All Files", ".*")],
        initialfile=default_name,
    )


def ask_open_path() -> Optional[str]:
    return filedialog.askopenfilename(
        title="Open",
        filetypes=[("JSON", ".json"), ("All Files", ".*")],
    )


# =============================================================================
# City coordinates for the Map (approximate) — only for known cities in dataset
# =============================================================================

CITY_COORDS: Dict[str, tuple] = {
    "Zurich": (47.3769, 8.5417),
    "Paris": (48.8566, 2.3522),
    "Berlin": (52.5200, 13.4050),
    "Sydney": (-33.8688, 151.2093),
    "Amsterdam": (52.3676, 4.9041),
    "Seoul": (37.5665, 126.9780),
    "Dubai": (25.2048, 55.2708),
    "Toronto": (43.6532, -79.3832),
    "Tokyo": (35.6762, 139.6503),
    "London": (51.5074, -0.1278),
    "New York": (40.7128, -74.0060),
    "Hong Kong": (22.3193, 114.1694),
    "Barcelona": (41.3851, 2.1734),
    "Johannesburg": (-26.2041, 28.0473),
    "Singapore": (1.3521, 103.8198),
    "Prague": (50.0755, 14.4378),
    "Lisbon": (38.7223, -9.1393),
    "Bangkok": (13.7563, 100.5018),
    "Mexico City": (19.4326, -99.1332),
}

# =============================================================================
# Main Application
# =============================================================================

class NomadUI(tk.Tk):
    """Top-level application window with left navigation + stacked pages."""

    PAGES = [
        ("Home", "home"),            # renamed from Dashboard
        ("Plan Trip", "plan"),
        ("Data Explorer", "data"),
        ("Saved", "saved"),
        ("Compare", "compare"),
        ("Settings", "settings"),
    ]

    def __init__(self):
        super().__init__()
        self.title("Digital Nomad Recommendation System - Blue Team")
        self.geometry("1220x820")
        self.minsize(1100, 720)

        self.status_var = tk.StringVar(value="Ready.")
        self.state = AppState()
        self._load_plans_from_disk()

        # ttk theme + global styles
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self._apply_theme()

        # Build UI
        self._create_header()
        self._create_menubar()
        self._create_statusbar()
        self._create_body()  # toolbar removed per request

        # Gently useful keybindings
        self.bind_all("<Control-n>", lambda e: self.new_plan())
        self.bind_all("<Control-s>", lambda e: self.file_save_state())
        self.bind_all("<Control-o>", lambda e: self.file_open_state())
        self.bind_all("<F1>", lambda e: self.show_about())
        # Ask for data mode immediately at startup
        self.after(150, self._prompt_for_data_mode)

    def _prompt_for_data_mode(self) -> None:
        """
        On app launch, ask the user to choose how this session loads data.

        This desktop build runs entirely on your machine. A production deployment
        would refresh data once per day on a server and the app would read that
        cloud copy instead of scraping interactively.

        Options:
        • Download fresh data now (may take a while): scrape sources and build today's dataset.
        • Use local cache only (no downloads): load the most recent dataset already saved on this computer.
        """
        msg = (
            "How should this session load its data?\n\n"
            "Option 1 (Yes) — Download fresh data now (slower):\n"
            "  Scrape sources and build today's dataset. This can take a while.\n\n"
            "Option 2 (No) — Use local cache only (faster):\n"
            "  Load the most recent dataset already saved on this computer.\n\n"
            "Note: This is a lightweight desktop build. A full service would refresh\n"
            "data daily on a server and the app would read that cloud snapshot.\n\n"
            "Do you want to download fresh data now?"
        )
        try:
            wants_fresh = messagebox.askyesno(
                "Data source for this session", msg, icon="question", default="yes"
            )
        except Exception:
            # Safe default if dialogs cannot be shown
            wants_fresh = True

        # Map user choice to a single boolean that drives behavior in the engine.
        # True  -> cache-only mode (NEVER scrape; load latest cache on disk)
        # False -> regular mode (use today's cache else scrape once)
        set_cache_only_mode(not wants_fresh)

        self.status("Data mode: " + ("Local cache only" if not wants_fresh else "Fresh download"))

    # --------------------------
    # UI Construction
    # --------------------------
    def _create_header(self) -> None:
        """Top header with brand (top-left)."""
        header = ttk.Frame(self, padding=(10, 6))
        header.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(header, text="Blue Team", style="Brand.TLabel").pack(side=tk.LEFT)

    def _create_menubar(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Plan\tCtrl+N", command=self.new_plan)
        file_menu.add_separator()
        file_menu.add_command(label="Save UI State…\tCtrl+S", command=self.file_save_state)
        file_menu.add_command(label="Open UI State…\tCtrl+O", command=self.file_open_state)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_exit)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Toggle Theme", command=self.toggle_theme)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Quick Tips", command=self.show_help)
        help_menu.add_command(label="About\tF1", command=self.show_about)

        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_cascade(label="View", menu=view_menu)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def _create_body(self) -> None:
        """Left navigation + stacked pages."""
        body = ttk.Frame(self); body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Sidebar
        self.sidebar = ttk.Frame(body, width=220)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Label(self.sidebar, text="Navigation", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=12, pady=(12, 6)
        )
        self.nav_list = tk.Listbox(self.sidebar, activestyle="dotbox", exportselection=False)
        for title, key in self.PAGES:
            self.nav_list.insert(tk.END, title)
        self.nav_list.selection_set(0)
        self.nav_list.bind("<<ListboxSelect>>", self._on_nav_select)
        self.nav_list.pack(fill=tk.BOTH, expand=True, padx=12)

        # Sidebar quick actions
        actions = ttk.Frame(self.sidebar)
        actions.pack(fill=tk.X, padx=12, pady=(6, 12))
        ttk.Button(actions, text="New Plan", command=self.new_plan).pack(fill=tk.X)
        #ttk.Button(actions, text="Export Results CSV", command=self.export_results_csv).pack(fill=tk.X, pady=(6, 0))

        # Main area (stack)
        self.main_area = ttk.Frame(body); self.main_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.pages: Dict[str, tk.Frame] = {}
        self._build_pages()
        self.show_page("home")

    def _create_statusbar(self) -> None:
        ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(8, 2)).pack(side=tk.BOTTOM, fill=tk.X)

    def _build_pages(self) -> None:
        self.pages["home"] = HomePage(self.main_area, self)
        self.pages["plan"] = PlanTripPage(self.main_area, self)       # now with Map + Dashboard tabs
        self.pages["data"] = DataExplorerPage(self.main_area, self)   # already handles "-"
        self.pages["saved"] = SavedPage(self.main_area, self)         # with search bar
        self.pages["compare"] = ComparePage(self.main_area, self)     # plan selection preserved
        self.pages["settings"] = SettingsPage(self.main_area, self)
        for page in self.pages.values():
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

    # --------------------------
    # Theming
    # --------------------------
    def toggle_theme(self) -> None:
        order = ["light", "dark", "blue"]
        try:
            idx = order.index(self.state.theme)
        except ValueError:
            idx = 0
        self.state.theme = order[(idx + 1) % len(order)]
        self._apply_theme()
        self.status(f"Theme set to {self.state.theme.title()}")

    def _apply_theme(self) -> None:
        theme = self.state.theme
        if theme == "dark":
            bg, fg, accent = "#111827", "#e5e7eb", "#3b82f6"
        elif theme == "blue":
            bg, fg, accent = "#e8f0fe", "#0f172a", "#2563eb"
        else:
            bg, fg, accent = "#f8fafc", "#111827", "#2563eb"
        self.configure(bg=bg)
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("TButton", padding=6)
        self.style.configure("TEntry", fieldbackground="#ffffff")
        self.style.configure("Brand.TLabel", background=bg, foreground=accent, font=("Segoe UI", 24, "bold"))
        self.style.map("TButton", foreground=[("active", fg)], background=[("active", accent)])

    # --------------------------
    # Navigation & Status
    # --------------------------
    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if not page:
            return
        for p in self.pages.values():
            p.place_forget()
        page.place(relx=0, rely=0, relwidth=1, relheight=1)
        for idx, (_, k) in enumerate(self.PAGES):
            if k == key:
                self.nav_list.selection_clear(0, tk.END)
                self.nav_list.selection_set(idx)
                break

        # Keep Compare plan choices up-to-date whenever the page is shown
        if key == "compare":
            compare_page: "ComparePage" = self.pages["compare"]  # type: ignore
            compare_page.refresh_plan_choices()

        self.status(f"Viewing: {key.title()}")

    def _on_nav_select(self, _) -> None:
        sel = self.nav_list.curselection()
        if not sel:
            return
        self.show_page(self.PAGES[sel[0]][1])

    def status(self, text: str) -> None:
        self.status_var.set(text)

    # --------------------------
    # Menu Actions
    # --------------------------
    def new_plan(self) -> None:
        self.show_page("plan")
        page: "PlanTripPage" = self.pages["plan"]  # type: ignore
        page.reset_filters()
        self.status("New plan created.")

    def file_save_state(self) -> None:
        path = ask_save_path("ui_state.json")
        if not path:
            return
        data = {
            "theme": self.state.theme,
            "default_region": self.state.default_region,
            "saved_plans": [plan.__dict__ for plan in self.state.saved_plans],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.status(f"UI state saved to {os.path.basename(path)}")
        messagebox.showinfo("Save", "UI state saved.")

    def file_open_state(self) -> None:
        path = ask_open_path()
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.state.theme = data.get("theme", self.state.theme)
            self.state.default_region = data.get("default_region", self.state.default_region)
            plans = [Plan(**p) for p in data.get("saved_plans", [])]
            self.state.saved_plans = plans
            _write_plans_store([p.__dict__ for p in plans])

            self._apply_theme()
            saved: "SavedPage" = self.pages["saved"]  # type: ignore
            saved.refresh()

            self.status(f"Loaded UI state from {os.path.basename(path)}")
            messagebox.showinfo("Open", "UI state loaded.")
        except Exception as e:
            messagebox.showerror("Open", f"Failed to open file.\n\n{e}")

    def export_results_csv(self) -> None:
        """Export a CSV template. (Keeps this lightweight for now.)"""
        path = filedialog.asksaveasfilename(
            title="Export Results CSV",
            defaultextension=".csv",
            filetypes=[("CSV", ".csv"), ("All Files", ".*")],
            initialfile="recommendations.csv",
        )
        if not path:
            return
        headers = ["City", "Country", "Visa-Free", "Monthly Cost (USD)", "Avg Internet (Mbps)", "Score"]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(",".join(headers) + "\n")
            messagebox.showinfo("Export", "Export complete (empty template with headers).")
            self.status("Results CSV template exported.")
        except Exception as e:
            messagebox.showerror("Export", f"Failed to export.\n\n{e}")

    def show_help(self) -> None:
        tips = (
            "• Use the left navigation to switch pages.\n"
            "• ‘Plan Trip’ lets you set filters and request recommendations.\n"
            "• Save your UI state from File → Save UI State….\n"
            "• Toggle themes from View → Toggle Theme or pick a theme in Settings.\n"
            "• Saved plans persist to disk and can be reopened later."
        )
        messagebox.showinfo("Quick Tips", tips)

    def show_about(self) -> None:
        messagebox.showinfo(
            "About",
            "Digital Nomad Recommendation System\n\n"
            "Plan smarter with consolidated visa, cost of living, and internet speed data.\n"
            "Created by Blue Team as a Data Focused Python (95888-C1) final project.\n",
            "Team Members:\n",
            "• Arturo Arias\n",
            "• Madison Shen\n",
            "• Jiafu Wang\n",
            "• Jiaqi Xu\n",
            "• Jiaming Zhu\n",
        )

    def on_exit(self) -> None:
        self.destroy()

    def _load_plans_from_disk(self) -> None:
        """Initial load of saved plans."""
        try:
            raw_plans = load_all_plans_from_store()
            self.state.saved_plans = [Plan(**p) for p in raw_plans]
        except Exception:
            self.state.saved_plans = []


# =============================================================================
# Page: Home (renamed from Dashboard)
# =============================================================================

class HomePage(ttk.Frame):
    def __init__(self, parent, app: NomadUI):
        super().__init__(parent)
        self.app = app

        header = ttk.Label(self, text="Welcome, Digital Nomad!", font=("Segoe UI", 16, "bold"))
        sub = ttk.Label(
            self,
            text=(
                "Plan smarter with consolidated visa, cost of living, and internet speed data.\n"
                "Use the sidebar to navigate and the planner to request recommendations."
            ),
        )
        cta = ttk.Button(self, text="Start a New Plan", command=self.app.new_plan)

        header.pack(anchor="w", padx=18, pady=(18, 6))
        sub.pack(anchor="w", padx=18)
        cta.pack(anchor="w", padx=18, pady=12)

        sep = ttk.Separator(self); sep.pack(fill=tk.X, padx=18, pady=12)

        quick = ttk.Frame(self); quick.pack(fill=tk.BOTH, expand=True, padx=18, pady=6)
        QuickLink(quick, text="Plan Trip", cmd=lambda: app.show_page("plan")).grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        QuickLink(quick, text="Data Explorer", cmd=lambda: app.show_page("data")).grid(row=0, column=1, padx=8, pady=8, sticky="nsew")
        QuickLink(quick, text="Saved Plans", cmd=lambda: app.show_page("saved")).grid(row=0, column=2, padx=8, pady=8, sticky="nsew")
        QuickLink(quick, text="Settings", cmd=lambda: app.show_page("settings")).grid(row=0, column=3, padx=8, pady=8, sticky="nsew")

        for i in range(4):
            quick.columnconfigure(i, weight=1)
        quick.rowconfigure(0, weight=1)


class QuickLink(ttk.Frame):
    def __init__(self, parent, text: str, cmd):
        super().__init__(parent, padding=16)
        ttk.Label(self, text=text, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Button(self, text="Open", command=cmd).pack(anchor="w", pady=(8, 0))


# =============================================================================
# Page: Plan Trip (Table + Map + Dashboard)
# =============================================================================

class PlanTripPage(ttk.Frame):
    """Planner page: filter inputs + results table + map + dashboard."""

    def __init__(self, parent, app: NomadUI):
        super().__init__(parent)
        self.app = app

        # To render charts/maps from the last recommendation call
        self.last_df_table = None    # formatted for table (strings)
        self.last_df_raw = None      # numeric values for plotting

        # ---------------- Filters Panel ----------------
        filters = ttk.Labelframe(self, text="Filters", padding=12)
        filters.pack(side=tk.TOP, fill=tk.X, padx=18, pady=(18, 6))

        self.var_budget = tk.StringVar()
        self.var_duration = tk.StringVar()
        self.var_depart_month = tk.StringVar()
        self.var_region = tk.StringVar(value=self.app.state.default_region)
        self.var_requires_visa_free = tk.BooleanVar(value=True)
        self.var_min_downlink = tk.StringVar(value="25")

        ttk.Label(filters, text="Monthly Budget (USD)").grid(row=0, column=0, sticky="w")
        ttk.Entry(filters, textvariable=self.var_budget, width=18).grid(row=1, column=0, sticky="w")

        ttk.Label(filters, text="Trip Duration (weeks)").grid(row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Entry(filters, textvariable=self.var_duration, width=18).grid(row=1, column=1, sticky="w", padx=(18, 0))

        ttk.Label(filters, text="Departure Month").grid(row=0, column=2, sticky="w", padx=(18, 0))
        ttk.Combobox(filters, textvariable=self.var_depart_month, values=self._months(), width=16).grid(
            row=1, column=2, sticky="w", padx=(18, 0)
        )

        ttk.Label(filters, text="Region").grid(row=0, column=3, sticky="w", padx=(18, 0))
        ttk.Combobox(
            filters,
            textvariable=self.var_region,
            values=["Global", "Europe", "Asia", "Americas", "Africa", "Oceania"],
            width=16,
        ).grid(row=1, column=3, sticky="w", padx=(18, 0))

        ttk.Checkbutton(filters, text="Visa-free or e-visa only", variable=self.var_requires_visa_free).grid(
            row=2, column=0, columnspan=2, pady=(10, 0), sticky="w"
        )

        ttk.Label(filters, text="Minimum Internet Speed (Mbps)").grid(row=0, column=4, sticky="w", padx=(18, 0))
        ttk.Entry(filters, textvariable=self.var_min_downlink, width=10).grid(row=1, column=4, sticky="w", padx=(18, 0))

        for c in range(5):
            filters.columnconfigure(c, weight=1)

        # ---------------- Action Buttons ----------------
        btns = ttk.Frame(self)
        btns.pack(side=tk.TOP, fill=tk.X, padx=18, pady=(6, 6))
        ttk.Button(btns, text="Get Recommendations", command=self.on_get_recs).pack(side=tk.LEFT)
        ttk.Button(btns, text="Save Plan", command=self.on_save_plan).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="Reset Filters", command=self.reset_filters).pack(side=tk.LEFT, padx=(8, 0))

        # ---------------- Results (Notebook) ----------------
        wrap = ttk.Labelframe(self, text="Results", padding=8)
        wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=18, pady=(6, 18))
        self.nb_results = ttk.Notebook(wrap); self.nb_results.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Table
        self.tab_table = ttk.Frame(self.nb_results)
        self.nb_results.add(self.tab_table, text="Table")
        cols = ("city", "country", "visa_free", "monthly_cost", "avg_internet_mbps", "nomad_score")
        self.tree = ttk.Treeview(self.tab_table, columns=cols, show="headings", height=18)
        headings = [
            ("city", "City"),
            ("country", "Country"),
            ("visa_free", "Visa-Free"),
            ("monthly_cost", "Monthly Cost (USD)"),
            ("avg_internet_mbps", "Avg Internet (Mbps)"),
            ("nomad_score", "Score"),
        ]
        for key, label in headings:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=150 if key != "city" else 180, anchor="center")
        default_font = tkfont.nametofont("TkDefaultFont")
        self._font_bold = tkfont.Font(
            family=default_font.actual("family"),
            size=default_font.actual("size"),
            weight="bold",
        )
        self.tree.tag_configure("top1", foreground="#2563eb", font=self._font_bold)
        vsb = ttk.Scrollbar(self.tab_table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Tab 2: Map (now with real map background)
        self.tab_map = ttk.Frame(self.nb_results)
        self.nb_results.add(self.tab_map, text="Map")
        self.fig_map = plt.Figure(figsize=(7.6, 4.8), dpi=100)
        self.ax_map = self.fig_map.add_subplot(111)
        self.ax_map.set_title("Recommendations Map")
        self.canvas_map = FigureCanvasTkAgg(self.fig_map, master=self.tab_map)
        self.canvas_map.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Tab 3: Dashboard (text + two bar charts + visa pie)
        self.tab_dash = ttk.Frame(self.nb_results)
        self.nb_results.add(self.tab_dash, text="Dashboard")

        self.lbl_reco = ttk.Label(self.tab_dash, text="Recommended destination: —", font=("Segoe UI", 12, "bold"))
        self.lbl_reco.pack(anchor="w", padx=8, pady=(4, 6))

        charts = ttk.Frame(self.tab_dash); charts.pack(fill=tk.BOTH, expand=True)
        # Cost bar
        self.fig_cost = plt.Figure(figsize=(4.5, 3.5), dpi=100)
        self.ax_cost = self.fig_cost.add_subplot(111)
        self.ax_cost.set_title("Monthly Cost (USD)")
        self.ax_cost.tick_params(axis="x", rotation=30)
        self.canvas_cost = FigureCanvasTkAgg(self.fig_cost, master=charts)
        self.canvas_cost.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # Speed bar
        self.fig_speed = plt.Figure(figsize=(4.5, 3.5), dpi=100)
        self.ax_speed = self.fig_speed.add_subplot(111)
        self.ax_speed.set_title("Average Internet Speed (Mbps)")
        self.ax_speed.tick_params(axis="x", rotation=30)
        self.canvas_speed = FigureCanvasTkAgg(self.fig_speed, master=charts)
        self.canvas_speed.get_tk_widget().grid(row=0, column=1, sticky="nsew", padx=6, pady=6)

        # Visa pie
        self.fig_visa = plt.Figure(figsize=(4.5, 3.5), dpi=100)
        self.ax_visa = self.fig_visa.add_subplot(111)
        self.ax_visa.set_title("Visa Restrictions")
        self.canvas_visa = FigureCanvasTkAgg(self.fig_visa, master=charts)
        self.canvas_visa.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        charts.columnconfigure(0, weight=1)
        charts.columnconfigure(1, weight=1)
        charts.rowconfigure(0, weight=1)
        charts.rowconfigure(1, weight=1)

        # Draw an empty map initially so the tab doesn't look blank
        self._render_map(None)

    # ----- Helpers -----
    def _months(self) -> List[str]:
        return [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]

    def current_filters(self) -> Dict[str, Any]:
        return {
            "budget": self.var_budget.get().strip(),
            "duration_weeks": self.var_duration.get().strip(),
            "depart_month": self.var_depart_month.get().strip(),
            "region": self.var_region.get().strip(),
            "visa_free_only": bool(self.var_requires_visa_free.get()),
            "min_downlink": (self.var_min_downlink.get() or "").strip(),
        }

    # ----- Actions -----
    def on_get_recs(self) -> None:
        """Fetch recommendations and update the table + map + dashboard."""
        filters = self.current_filters()

        # Robust budget parsing with friendly message
        raw = (self.var_budget.get() or "").strip()
        norm = re.sub(r"[^0-9.\-]", "", raw)
        try:
            budget_val = float(norm) if norm else 0.0
        except Exception:
            budget_val = 0.0

        if budget_val <= 0:
            messagebox.showinfo("Recommendations", "Please enter a positive monthly budget in USD (e.g., 2000).")
            self.app.status("Invalid budget.")
            return

        filters["budget"] = str(budget_val)

        # Call the engine and show specific errors for COLI fetching
        try:
            df = build_recommendations(filters)
        except CostOfLivingRateLimitError as e:
            messagebox.showerror(
                "Temporarily rate-limited",
                "Cost of living data is temporarily unavailable (HTTP 429 rate limit).\n"
                "Please wait ~2–5 minutes and try again.\n\nDetails:\n" + str(e)
            )
            return
        except CostOfLivingFetchError as e:
            messagebox.showerror(
                "Couldn’t fetch cost data",
                "We couldn’t fetch cost of living data right now.\n"
                "Please try again shortly.\n\nDetails:\n" + str(e)
            )
            return
        except NoCachedDataError:
            messagebox.showinfo(
                "No local data available",
                "You selected the quick start that avoids downloading, but there is no "
                "local dataset on disk yet.\n\n"
                "Restart the app and choose “Download fresh data now” to build the dataset once."
            )
            self.app.status("No local cache available; fresh download required.")
            return
        except Exception as e:
            print("Error in build_recommendations:", e)

        # Clear previous table rows
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        if df is None:
            messagebox.showinfo("Recommendations", "Please enter a positive monthly budget in USD (e.g., 2000).")
            self.app.status("Invalid budget.")
            return

        if df.empty:
            messagebox.showinfo(
                "Recommendations",
                "No destinations matched your filters.\n"
                "Try increasing your budget, lowering the minimum Mbps, or unchecking the visa restriction.",
            )
            self.app.status("No matching destinations.")
            self._render_map(None)
            self._render_dashboard(None)
            return

        # Preserve a raw numeric copy for plotting
        self.last_df_raw = df.copy()

        # Nice rounding for display; '-' for NaN (table)
        def fmt_num(v: Any) -> str:
            try:
                f = float(v)
                if math.isnan(f):
                    return "-"
                return f"{f:.2f}"
            except Exception:
                s = "" if v is None else str(v).strip()
                return "-" if s == "" or s.lower() in ("nan", "na", "none") else s

        table_df = df.copy()
        for col in ("monthly_cost", "avg_internet_mbps", "nomad_score"):
            if col in table_df.columns:
                table_df[col] = table_df[col].apply(fmt_num)

        self.last_df_table = table_df

        # Populate table (tag top row)
        for idx, row in enumerate(table_df.itertuples(index=False)):
            tags = ("top1",) if idx == 0 else ()
            self.tree.insert(
                "",
                tk.END,
                values=(
                    getattr(row, "city", ""),
                    getattr(row, "country", ""),
                    getattr(row, "visa_free", ""),
                    getattr(row, "monthly_cost", "-"),
                    getattr(row, "avg_internet_mbps", "-"),
                    getattr(row, "nomad_score", "-"),
                ),
                tags=tags,
            )

        # Update Map & Dashboard
        self._render_map(self.last_df_raw)
        self._render_dashboard(self.last_df_raw)

        self.app.status("Recommendations updated.")

    def on_save_plan(self) -> None:
        filters = self.current_filters()
        plan_name = f"Plan {datetime.now().strftime('%Y%m%d-%H%M%S')}"
        plan = Plan(id=plan_name, name=plan_name, created_at=now_iso(), filters=filters)
        self.app.state.saved_plans.append(plan)
        save_plan_to_store(plan.__dict__)
        saved: "SavedPage" = self.app.pages["saved"]  # type: ignore
        saved.refresh()
        messagebox.showinfo("Plan Saved", f"Saved filter set as ‘{plan_name}’.")
        self.app.status(f"Saved plan: {plan_name}")

    def reset_filters(self) -> None:
        self.var_budget.set("")
        self.var_duration.set("")
        self.var_depart_month.set("")
        self.var_region.set(self.app.state.default_region)
        self.var_requires_visa_free.set(True)
        self.var_min_downlink.set("25")
        self.app.status("Filters reset.")
        # Clear table
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        # Clear visuals
        self._render_map(None)
        self._render_dashboard(None)

    # ----- Visualization helpers -----
    def _render_map(self, df):
        """
        Render the Recommendations Map using a PNG world background.

        Assumes a file named 'world_map.png' lives in the SAME folder as this file.
        The image is drawn with geographic extents (-180..180 lon, -90..90 lat) so
        city coordinates align. Falls back to a simple ocean color if the image
        cannot be loaded (but does NOT draw the old generated polygons).

        Expected instance attrs:
        - self.ax_map (matplotlib Axes)
        - self.fig_map (matplotlib Figure)
        - self.canvas_map (FigureCanvasTkAgg)
        - CITY_COORDS (dict: city -> (lat, lon))
        """
        

        # Remove an existing colorbar (if any) so we don't stack them on refresh
        if hasattr(self, "_map_cbar") and self._map_cbar:
            try:
                self._map_cbar.remove()
            except Exception:
                pass
            self._map_cbar = None

        self.ax_map.clear()
        self.ax_map.set_title("Recommendations Map")

        # Try to load ./world_map.png (relative to this file or CWD)
        bg_loaded = False
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_map.png"),
            "world_map.png",
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    img = imread(path)
                    # Anchor the image to world lon/lat bounds
                    self.ax_map.imshow(
                        img,
                        extent=(-180, 180, -90, 90),
                        origin="upper",
                        aspect="auto",
                        zorder=0,
                    )
                    bg_loaded = True
                    break
            except Exception:
                # Try the next candidate
                pass

        # Establish axes limits either way
        self.ax_map.set_xlim(-180, 180)
        self.ax_map.set_ylim(-90, 90)

        # Simple fallback if the PNG isn't available
        if not bg_loaded:
            self.ax_map.set_facecolor("#cae9ff")
            self.ax_map.grid(True, linestyle="--", alpha=0.25, linewidth=0.5)

        # No data? Show a friendly message over the background
        if df is None or df.empty:
            self.ax_map.text(
                0.5, 0.5, "No data",
                ha="center", va="center",
                transform=self.ax_map.transAxes,
                fontsize=11, color="#374151",
                zorder=20,
            )
            self.canvas_map.draw()
            return

        # Build plotting arrays and scale by nomad_score
        lats, lons, sizes, colors = [], [], [], []
        try:
            smin = float(df["nomad_score"].min()); smax = float(df["nomad_score"].max())
        except Exception:
            smin, smax = 0.0, 1.0
        spread = (smax - smin) if smax != smin else 1.0

        for r in df.to_dict(orient="records"):
            city = str(r.get("city") or "").strip()
            if city not in CITY_COORDS:
                continue
            lat, lon = CITY_COORDS[city]
            score = float(r.get("nomad_score", 0.0) or 0.0)
            size = 50.0 + 300.0 * ((score - smin) / spread)      # 50..350
            color = 0.25 + 0.75 * ((score - smin) / spread)       # 0.25..1 (for cmap)
            lats.append(lat); lons.append(lon); sizes.append(size); colors.append(color)

        if not lats:
            self.ax_map.text(
                0.5, 0.5, "No mappable cities in results",
                ha="center", va="center",
                transform=self.ax_map.transAxes,
                fontsize=11, color="#374151",
                zorder=20,
            )
            self.canvas_map.draw()
            return

        # Plot markers over the map
        sc = self.ax_map.scatter(
            lons, lats,
            s=sizes, c=colors, cmap="Blues",
            alpha=0.9, edgecolor="k", linewidth=0.6, zorder=10
        )

        # Emphasize the top city with an orange ring
        try:
            idx_top = int(df["nomad_score"].idxmax())
            top_city = str(df.loc[idx_top, "city"])
            if top_city in CITY_COORDS:
                tlat, tlon = CITY_COORDS[top_city]
                self.ax_map.scatter(
                    [tlon], [tlat],
                    s=420, facecolors="none", edgecolors="#ff5722",
                    linewidth=2.2, zorder=12
                )
        except Exception:
            pass

        # Colorbar legend (store handle so we can remove on refresh)
        self._map_cbar = self.fig_map.colorbar(sc, ax=self.ax_map, fraction=0.035, pad=0.04)
        self._map_cbar.set_label("Relative Score Intensity")

        # Subtle axis labels
        self.ax_map.set_xlabel("Longitude")
        self.ax_map.set_ylabel("Latitude")

        self.canvas_map.draw()

    def _render_dashboard(self, df):
        """
        Dashboard with:
        • horizontal bar chart for Monthly Cost (USD) — five countries with the lowest average cost of living
        • horizontal bar chart for Average Internet Speed (Mbps) — five countries with the highest average internet speed
        • pie chart for Visa Restrictions

        Layout goals:
        • Allocate *much more* space to the labels (left side) and a narrow area to the bars.
        • Keep ONLY the barplot titles centered (using figure-level suptitle so centering isn't affected by subplot shifts).
        """

        # Clear axes
        for ax in (self.ax_cost, self.ax_speed, self.ax_visa):
            ax.clear()

        # Remove any previous figure-level suptitles so they don't stack
        for fig in (self.fig_cost, self.fig_speed):
            if getattr(fig, "_suptitle", None) is not None:
                try:
                    fig._suptitle.remove()
                except Exception:
                    pass
                fig._suptitle = None

        if df is None or df.empty:
            self.lbl_reco.configure(text="Recommended destination: —")
            self.ax_cost.text(0.5, 0.5, "No data", ha="center", va="center", transform=self.ax_cost.transAxes)
            self.ax_speed.text(0.5, 0.5, "No data", ha="center", va="center", transform=self.ax_speed.transAxes)
            self.ax_visa.text(0.5, 0.5, "No data", ha="center", va="center", transform=self.ax_visa.transAxes)
            self.canvas_cost.draw(); self.canvas_speed.draw(); self.canvas_visa.draw()
            return

        # Recommended destination (top nomad_score)
        try:
            best = df.sort_values("nomad_score", ascending=False).iloc[0]
            self.lbl_reco.configure(
                text=f"Recommended destination: {best.get('city', '—')}, {best.get('country', '—')}"
            )
        except Exception:
            self.lbl_reco.configure(text="Recommended destination: —")

        # Helper to compute a big left margin based on the longest label
        def _left_margin(names, base=0.45, per_char=0.012, max_left=0.86):
            longest = max((len(str(n)) for n in names), default=0)
            return min(max_left, base + per_char * longest)

        # ----------------------------- Monthly Cost (USD) -----------------------------
        try:
            cost_tbl = (
                df.loc[:, ["country", "monthly_cost"]]
                .assign(monthly_cost=pd.to_numeric(df["monthly_cost"], errors="coerce"))
                .dropna(subset=["country", "monthly_cost"])
            )
            if cost_tbl.empty:
                raise ValueError("No valid cost data")

            cost_agg = cost_tbl.groupby("country", as_index=False)["monthly_cost"].mean()
            bottom5_cost = cost_agg.nsmallest(5, "monthly_cost")

            countries_cost = bottom5_cost["country"].astype(str).tolist()
            costs = bottom5_cost["monthly_cost"].tolist()

            # Give labels lots of room; keep bars narrow
            lm = _left_margin(countries_cost)
            self.fig_cost.subplots_adjust(left=lm, right=0.98, top=0.82, bottom=0.18)

            self.ax_cost.barh(countries_cost, costs, height=0.4)
            # Axis labels; title handled by figure-level suptitle for true centering
            self.ax_cost.set_xlabel("USD")
            self.ax_cost.set_ylabel("Country")
            self.ax_cost.invert_yaxis()
            self.ax_cost.grid(axis="x", linestyle="--", alpha=0.25)
            self.ax_cost.tick_params(axis="y", pad=8)

            # Centered title across the whole figure (not just the shrunken subplot)
            self.fig_cost._suptitle = self.fig_cost.suptitle(
                "Lowest Monthly Cost — Top 5 Countries", y=0.98, ha="center"
            )
        except Exception:
            self.ax_cost.text(0.5, 0.5, "Cost data error", ha="center", va="center", transform=self.ax_cost.transAxes)

        # ---------------------- Average Internet Speed (Mbps) -------------------------
        try:
            speed_tbl = (
                df.loc[:, ["country", "avg_internet_mbps"]]
                .assign(avg_internet_mbps=pd.to_numeric(df["avg_internet_mbps"], errors="coerce"))
                .dropna(subset=["country", "avg_internet_mbps"])
            )
            if speed_tbl.empty:
                raise ValueError("No valid speed data")

            speed_agg = speed_tbl.groupby("country", as_index=False)["avg_internet_mbps"].mean()
            top5_speed = speed_agg.nlargest(5, "avg_internet_mbps")

            countries_speed = top5_speed["country"].astype(str).tolist()
            speeds = top5_speed["avg_internet_mbps"].tolist()

            lm = _left_margin(countries_speed)
            self.fig_speed.subplots_adjust(left=lm, right=0.98, top=0.82, bottom=0.18)

            self.ax_speed.barh(countries_speed, speeds, height=0.4)
            self.ax_speed.set_xlabel("Mbps")
            self.ax_speed.set_ylabel("Country")
            self.ax_speed.invert_yaxis()
            self.ax_speed.grid(axis="x", linestyle="--", alpha=0.25)
            self.ax_speed.tick_params(axis="y", pad=8)

            self.fig_speed._suptitle = self.fig_speed.suptitle(
                "Highest Average Internet Speed — Top 5 Countries", y=0.98, ha="center"
            )
        except Exception:
            self.ax_speed.text(0.5, 0.5, "Speed data error", ha="center", va="center", transform=self.ax_speed.transAxes)

        # ----------------------------- Visa Restrictions ------------------------------
        try:
            free = int(df["visa_free"].astype(bool).sum())
            total = int(len(df))
            req = max(0, total - free)
            labels = ["Visa-Free", "Requires Visa"]
            sizes = [free, req] if (free + req) > 0 else [1, 0]
            self.ax_visa.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90)
            self.ax_visa.axis("equal")
            self.ax_visa.set_title("Visa Restrictions")
        except Exception:
            self.ax_visa.text(0.5, 0.5, "Visa data error", ha="center", va="center", transform=self.ax_visa.transAxes)

        # Draw canvases
        self.canvas_cost.draw()
        self.canvas_speed.draw()
        self.canvas_visa.draw()

# =============================================================================
# Page: Data Explorer  (functional; '-' for NaN)
# =============================================================================

class DataExplorerPage(ttk.Frame):
    """
    Three tabs to preview data, with simple query filters.
    - Visa Rules: shows (Country, Category, Note)
    - Cost of Living: shows core numeric columns per city (NaN→'-')
    - Internet Speed: merges mobile+fixed by country (NaN→'-')
    """

    def __init__(self, parent, app: NomadUI):
        super().__init__(parent)
        self.app = app

        nb = ttk.Notebook(self); nb.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)

        # Build each tab with its own table and refresh controls
        self.visa_tab = self._build_visa_tab(nb)
        self.coli_tab = self._build_coli_tab(nb)
        self.speed_tab = self._build_speed_tab(nb)

        nb.add(self.visa_tab["frame"], text="Visa Rules")
        nb.add(self.coli_tab["frame"], text="Cost of Living")
        nb.add(self.speed_tab["frame"], text="Internet Speed")

    # ---- Builders for each tab ----
    def _build_visa_tab(self, notebook: ttk.Notebook):
        frame = ttk.Frame(notebook)

        # Controls
        top = ttk.Frame(frame); top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Filter (country or category contains):").pack(side=tk.LEFT)
        var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=var, width=40); entry.pack(side=tk.LEFT, padx=(6, 6))
        entry.bind("<Return>", lambda e: self.on_refresh_visa(var.get()))
        ttk.Button(top, text="Refresh", command=lambda: self.on_refresh_visa(var.get())).pack(side=tk.LEFT)

        # Table
        table_wrap = ttk.Frame(frame); table_wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(12, 0))
        cols = ("country", "category", "note")
        tree = ttk.Treeview(table_wrap, columns=cols, show="headings")
        tree.heading("country", text="Country"); tree.heading("category", text="Category"); tree.heading("note", text="Note")
        tree.column("country", width=220); tree.column("category", width=360); tree.column("note", width=300)
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)

        return {"frame": frame, "var": var, "tree": tree}

    def _build_coli_tab(self, notebook: ttk.Notebook):
        frame = ttk.Frame(notebook)

        top = ttk.Frame(frame); top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Filter (city contains):").pack(side=tk.LEFT)
        var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=var, width=40); entry.pack(side=tk.LEFT, padx=(6, 6))
        entry.bind("<Return>", lambda e: self.on_refresh_coli(var.get()))
        ttk.Button(top, text="Refresh", command=lambda: self.on_refresh_coli(var.get())).pack(side=tk.LEFT)

        table_wrap = ttk.Frame(frame); table_wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(12, 0))
        cols = ("city", "rent", "utilities", "internet", "transport", "food", "monthly")
        tree = ttk.Treeview(table_wrap, columns=cols, show="headings")
        heads = [
            ("city", "City"),
            ("rent", "Rent (1BR)"),
            ("utilities", "Utilities"),
            ("internet", "Internet (60 Mbps)"),
            ("transport", "Transport (Pass)"),
            ("food", "Food Est."),
            ("monthly", "Monthly Cost"),
        ]
        for key, text in heads:
            tree.heading(key, text=text)
            tree.column(key, width=140 if key != "city" else 180, anchor="center")
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)

        return {"frame": frame, "var": var, "tree": tree}

    def _build_speed_tab(self, notebook: ttk.Notebook):
        frame = ttk.Frame(notebook)

        top = ttk.Frame(frame); top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Filter (country contains):").pack(side=tk.LEFT)
        var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=var, width=40); entry.pack(side=tk.LEFT, padx=(6, 6))
        entry.bind("<Return>", lambda e: self.on_refresh_speed(var.get()))
        ttk.Button(top, text="Refresh", command=lambda: self.on_refresh_speed(var.get())).pack(side=tk.LEFT)

        table_wrap = ttk.Frame(frame); table_wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(12, 0))
        cols = ("country", "mobile_mbps", "fixed_mbps")
        tree = ttk.Treeview(table_wrap, columns=cols, show="headings")
        tree.heading("country", text="Country")
        tree.heading("mobile_mbps", text="Mobile Mbps")
        tree.heading("fixed_mbps", text="Fixed Mbps")
        tree.column("country", width=240); tree.column("mobile_mbps", width=160); tree.column("fixed_mbps", width=160)
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)

        return {"frame": frame, "var": var, "tree": tree}

    # ---- Refresh handlers (real data; '-' for NaN) ----
    def on_refresh_visa(self, query: str) -> None:
        """Flatten dict into rows (Country, Category, Note)."""
        try:
            data = fetch_visa_data(query)
        except Exception as e:
            messagebox.showerror("Visa Data", f"Failed to fetch visa data.\n\n{e}")
            return

        tree: ttk.Treeview = self.visa_tab["tree"]  # type: ignore
        for iid in tree.get_children():
            tree.delete(iid)

        if not isinstance(data, dict) or not data:
            tree.insert("", tk.END, values=("-", "No data", "-"))
            self.app.status("No visa data.")
            return

        q = (query or "").strip().lower()
        added = 0
        for category, countries in data.items():
            cat_l = (category or "").lower()
            note = "-"
            if "visa-free" in cat_l:
                note = "Visa-free"
            elif "on arrival" in cat_l:
                note = "Visa on arrival"
            elif "electronic" in cat_l or "eta" in cat_l:
                note = "eTA"
            elif "e-visa" in cat_l:
                note = "e-Visa"
            elif "requiring" in cat_l or "require" in cat_l:
                note = "Visa required"

            for country in countries:
                row_ok = True
                if q:
                    row_ok = (q in (country or "").lower()) or (q in cat_l)
                if row_ok:
                    tree.insert("", tk.END, values=(country or "-", category or "-", note))
                    added += 1
        if added == 0:
            tree.insert("", tk.END, values=("-", "No matches", "-"))
        self.app.status(f"Visa data loaded. Rows: {added}")

    def on_refresh_coli(self, query: str) -> None:
        """Cost-of-living from cached combined dataset; NaN→'-'."""
        try:
            df = fetch_cost_of_living_data(query)
        except CostOfLivingRateLimitError as e:
            messagebox.showerror(
                "Temporarily rate-limited",
                "Cost of living data is temporarily unavailable (HTTP 429 rate limit).\n"
                "Please wait a few minutes and try again.\n\nDetails:\n" + str(e)
            )
            return
        except CostOfLivingFetchError as e:
            messagebox.showerror(
                "Couldn’t fetch cost data",
                "We couldn’t fetch cost of living data right now.\n"
                "Please try again shortly.\n\nDetails:\n" + str(e)
            )
            return
        except NoCachedDataError:
            messagebox.showinfo(
                "No local data available",
                "Cache-only mode is on, but no cached dataset was found.\n\n"
                "Restart and choose “Download fresh data now” to build the dataset."
            )
            return
        except Exception as e:
            messagebox.showerror("Cost of Living", f"Failed to fetch cost data.\n\n{e}")
            return

        tree: ttk.Treeview = self.coli_tab["tree"]  # type: ignore
        for iid in tree.get_children():
            tree.delete(iid)

        if df is None or df.empty or "city" not in df.columns:
            tree.insert("", tk.END, values=("-", "-", "-", "-", "-", "-", "-"))
            self.app.status("No cost-of-living data.")
            return

        def fmt(v: Any) -> str:
            try:
                f = float(v)
                return "-" if math.isnan(f) else f"{f:.2f}"
            except Exception:
                s = "" if v is None else str(v).strip()
                return "-" if s == "" or s.lower() in ("nan", "na", "none") else s

        q = (query or "").strip().lower()
        added = 0
        for row in df.to_dict(orient="records"):
            city = fmt(row.get("city"))
            if q and q not in str(row.get("city", "")).lower():
                continue
            rent = fmt(row.get("rent_1br_city_center_usd"))
            util = fmt(row.get("utilities_basic_usd"))
            net = fmt(row.get("internet_60mbps_usd"))
            trans = fmt(row.get("transport_monthly_pass_usd"))
            food = fmt(row.get("food_estimate_usd"))
            monthly = fmt(row.get("monthly_cost"))
            tree.insert("", tk.END, values=(city, rent, util, net, trans, food, monthly))
            added += 1
            if added >= 300:  # responsiveness guard
                break
        if added == 0:
            tree.insert("", tk.END, values=("-", "-", "-", "-", "-", "-", "No matches"))
        self.app.status(f"Cost-of-living data loaded. Rows: {added}")

    def on_refresh_speed(self, query: str) -> None:
        """Internet speed from cached combined dataset; NaN→'-'."""
        try:
            mobile_df, fixed_df = fetch_internet_speed_data(query)
        except NoCachedDataError:
            messagebox.showinfo(
                "No local data available",
                "Cache-only mode is on, but no cached dataset was found.\n\n"
                "Restart and choose “Download fresh data now” to build the dataset."
            )
            return
        except Exception as e:
            messagebox.showerror("Internet Speed", f"Failed to fetch speed data.\n\n{e}")
            return

        tree: ttk.Treeview = self.speed_tab["tree"]  # type: ignore
        for iid in tree.get_children():
            tree.delete(iid)

        def fmt(v: Any) -> str:
            try:
                f = float(v)
                return "-" if math.isnan(f) else f"{f:.2f}"
            except Exception:
                s = "" if v is None else str(v).strip()
                return "-" if s == "" or s.lower() in ("nan", "na", "none") else s

        if mobile_df is None and fixed_df is None:
            tree.insert("", tk.END, values=("-", "-", "-"))
            self.app.status("No speed data.")
            return

        merged_rows = 0
        fixed_map = {}
        if fixed_df is not None and not fixed_df.empty:
            for r in fixed_df.to_dict(orient="records"):
                fixed_map[(r.get("Country") or "").strip()] = r.get("fixed_mbps")

        if mobile_df is not None and not mobile_df.empty:
            for r in mobile_df.to_dict(orient="records"):
                country = (r.get("Country") or "").strip()
                mobile = r.get("mobile_mbps")
                fixed = fixed_map.get(country, None)
                tree.insert("", tk.END, values=(country or "-", fmt(mobile), fmt(fixed)))
                merged_rows += 1
                if merged_rows >= 400:
                    break
        else:
            for r in (fixed_df.to_dict(orient="records") if fixed_df is not None else []):
                country = (r.get("Country") or "").strip()
                fixed = r.get("fixed_mbps")
                tree.insert("", tk.END, values=(country or "-", "-", fmt(fixed)))
                merged_rows += 1
                if merged_rows >= 400:
                    break

        if merged_rows == 0:
            tree.insert("", tk.END, values=("-", "-", "No matches"))
        self.app.status(f"Internet speed data loaded. Rows: {merged_rows}")


# =============================================================================
# Page: Saved  (with search)
# =============================================================================

class SavedPage(ttk.Frame):
    """Index of saved plans with search, open, rename, delete, and export."""

    def __init__(self, parent, app: NomadUI):
        super().__init__(parent)
        self.app = app

        # Header + refresh
        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=18, pady=(18, 6))
        ttk.Label(top, text="Saved Plans", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        # Search bar for plan names (case-insensitive)
        search_bar = ttk.Frame(self); search_bar.pack(side=tk.TOP, fill=tk.X, padx=18, pady=(0, 6))
        ttk.Label(search_bar, text="Search Plans:").pack(side=tk.LEFT)
        self.var_search = tk.StringVar()
        e = ttk.Entry(search_bar, textvariable=self.var_search, width=32)
        e.pack(side=tk.LEFT, padx=(6, 6))
        e.bind("<KeyRelease>", lambda _: self.refresh())  # instant filtering
        ttk.Button(search_bar, text="Clear", command=lambda: (self.var_search.set(""), self.refresh())).pack(side=tk.LEFT)

        # Table
        table_wrap = ttk.Frame(self); table_wrap.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=18, pady=(6, 6))
        cols = ("name", "created", "region", "budget", "duration")
        self.tree = ttk.Treeview(table_wrap, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Name")
        self.tree.heading("created", text="Created")
        self.tree.heading("region", text="Region")
        self.tree.heading("budget", text="Budget")
        self.tree.heading("duration", text="Duration (weeks)")
        for c in cols:
            self.tree.column(c, width=160, anchor="center")
        vsb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Actions
        btns = ttk.Frame(self); btns.pack(side=tk.TOP, fill=tk.X, padx=18, pady=(6, 18))
        ttk.Button(btns, text="Open in Planner", command=self.open_in_planner).pack(side=tk.LEFT)
        ttk.Button(btns, text="Rename", command=self.rename_plan).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="Delete", command=self.delete_plan).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="Export Selected (JSON)", command=self.export_selected_json).pack(side=tk.LEFT, padx=(8, 0))

        self.refresh()

    def refresh(self) -> None:
        """Refresh table with current saved plans, filtered by the search box."""
        query = (self.var_search.get() if hasattr(self, "var_search") else "").strip().lower()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for plan in self.app.state.saved_plans:
            name = plan.name or ""
            if query and query not in name.lower():
                continue
            self.tree.insert(
                "",
                tk.END,
                iid=plan.id,
                values=(
                    name,
                    plan.created_at,
                    plan.filters.get("region", ""),
                    plan.filters.get("budget", ""),
                    plan.filters.get("duration_weeks", ""),
                ),
            )

    def _selected_plan(self) -> Optional[Plan]:
        sel = self.tree.selection()
        if not sel:
            return None
        pid = sel[0]
        for p in self.app.state.saved_plans:
            if p.id == pid:
                return p
        return None

    def open_in_planner(self) -> None:
        plan = self._selected_plan()
        if not plan:
            messagebox.showinfo("Open", "Please select a plan.")
            return
        page: "PlanTripPage" = self.app.pages["plan"]  # type: ignore

        f = plan.filters
        page.var_budget.set(f.get("budget", ""))
        page.var_duration.set(f.get("duration_weeks", ""))
        page.var_depart_month.set(f.get("depart_month", ""))
        page.var_region.set(f.get("region", self.app.state.default_region))
        page.var_requires_visa_free.set(f.get("visa_free_only", True))
        try:
            page.var_min_downlink.set(str(f.get("min_downlink", 25)))
        except Exception:
            page.var_min_downlink.set("25")

        self.app.show_page("plan")
        self.app.status(f"Loaded plan into planner: {plan.name}")

    def rename_plan(self) -> None:
        plan = self._selected_plan()
        if not plan:
            messagebox.showinfo("Rename", "Please select a plan.")
            return
        new_name = simple_prompt(self, title="Rename Plan", prompt="New name:", initial=plan.name)
        if not new_name:
            return
        plan.name = new_name
        rename_plan_in_store(plan.id, new_name)
        self.refresh()
        self.app.status(f"Renamed plan to: {new_name}")

    def delete_plan(self) -> None:
        plan = self._selected_plan()
        if not plan:
            messagebox.showinfo("Delete", "Please select a plan.")
            return
        if not messagebox.askyesno("Delete", f"Delete '{plan.name}'?"):
            return
        delete_plan_from_store(plan.id)
        self.app.state.saved_plans = [p for p in self.app.state.saved_plans if p.id != plan.id]
        self.refresh()
        self.app.status(f"Deleted plan: {plan.name}")

    def export_selected_json(self) -> None:
        plan = self._selected_plan()
        if not plan:
            messagebox.showinfo("Export", "Please select a plan.")
            return
        path = ask_save_path(f"{plan.name}.json")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(plan.__dict__, f, indent=2)
        messagebox.showinfo("Export", f"Exported {plan.name} to JSON.")
        self.app.status(f"Exported plan JSON: {os.path.basename(path)}")


# =============================================================================
# Page: Compare (plan selection preserved)
# =============================================================================

class ComparePage(ttk.Frame):
    """
    Side-by-side comparison of two saved plans.
    - User selects Plan A and Plan B via dropdowns.
    - Works with 0, 1, or 2+ saved plans (button disables when not enough).
    """

    def __init__(self, parent, app: NomadUI):
        super().__init__(parent)
        self.app = app

        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=18, pady=(18, 6))
        ttk.Label(top, text="Compare Saved Plans", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)

        # Selection row (Plan A / Plan B)
        sel = ttk.Frame(self); sel.pack(side=tk.TOP, fill=tk.X, padx=18, pady=(6, 6))

        ttk.Label(sel, text="Plan A:").pack(side=tk.LEFT)
        self.var_plan_a = tk.StringVar()
        self.cb_plan_a = ttk.Combobox(sel, textvariable=self.var_plan_a, width=28, state="readonly")
        self.cb_plan_a.pack(side=tk.LEFT, padx=(6, 18))

        ttk.Label(sel, text="Plan B:").pack(side=tk.LEFT)
        self.var_plan_b = tk.StringVar()
        self.cb_plan_b = ttk.Combobox(sel, textvariable=self.var_plan_b, width=28, state="readonly")
        self.cb_plan_b.pack(side=tk.LEFT, padx=(6, 18))

        self.btn_load = ttk.Button(sel, text="Load Selection", command=self.load_from_saved)
        self.btn_load.pack(side=tk.LEFT)

        # Compare tables
        mid = ttk.Frame(self); mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=18, pady=(6, 18))
        self.left_frame = self._build_compare_table(mid, "A")
        self.right_frame = self._build_compare_table(mid, "B")
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        # Initialize choices
        self.refresh_plan_choices()

    def refresh_plan_choices(self) -> None:
        """
        Populate the comboboxes with current saved plans.
        Handles 0/1-plan scenarios and disables the load button when needed.
        """
        names = [p.name for p in self.app.state.saved_plans]
        self.cb_plan_a["values"] = names
        self.cb_plan_b["values"] = names

        if len(names) == 0:
            self.var_plan_a.set("")
            self.var_plan_b.set("")
            self.cb_plan_a.configure(state="disabled")
            self.cb_plan_b.configure(state="disabled")
            self.btn_load.configure(state="disabled")
            # Clear tables
            self._fill_compare_tree(self.left_frame._tree, None)   # type: ignore
            self._fill_compare_tree(self.right_frame._tree, None)  # type: ignore
            self.app.status("No saved plans. Save a plan first to compare.")
            return

        if len(names) == 1:
            self.cb_plan_a.configure(state="readonly")
            self.cb_plan_b.configure(state="readonly")
            self.btn_load.configure(state="normal")
            self.var_plan_a.set(names[0])
            self.var_plan_b.set(names[0])
            self.app.status("Only one saved plan found. Comparing it to itself.")
            return

        # 2+ plans
        self.cb_plan_a.configure(state="readonly")
        self.cb_plan_b.configure(state="readonly")
        self.btn_load.configure(state="normal")
        self.var_plan_a.set(names[0])
        self.var_plan_b.set(names[1] if len(names) > 1 else names[0])

    def _build_compare_table(self, parent, title: str) -> ttk.Labelframe:
        frame = ttk.Labelframe(parent, text=f"Plan {title}", padding=8)
        tree = ttk.Treeview(frame, columns=("key", "value"), show="headings")
        tree.heading("key", text="Filter"); tree.heading("value", text="Value")
        tree.column("key", width=220); tree.column("value", width=300)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); vsb.pack(side=tk.RIGHT, fill=tk.Y)
        frame._tree = tree  # type: ignore
        return frame

    def _find_plan_by_name(self, name: str) -> Optional[Plan]:
        for p in self.app.state.saved_plans:
            if p.name == name:
                return p
        return None

    def load_from_saved(self) -> None:
        """Load user-selected plans into A/B. Handles <2 plan cases politely."""
        if len(self.app.state.saved_plans) == 0:
            messagebox.showinfo("Compare", "Please save one or more plans first.")
            return

        name_a = self.var_plan_a.get().strip()
        name_b = self.var_plan_b.get().strip()

        # Fallback defaults if fields are empty
        if not name_a:
            name_a = self.app.state.saved_plans[0].name
        if not name_b:
            name_b = name_a if len(self.app.state.saved_plans) == 1 else self.app.state.saved_plans[1].name

        plan_a = self._find_plan_by_name(name_a)
        plan_b = self._find_plan_by_name(name_b)

        if not plan_a and not plan_b:
            messagebox.showinfo("Compare", "Selected plans not found. Please reselect.")
            self.refresh_plan_choices()
            return

        if not plan_a:
            messagebox.showinfo("Compare", "Plan A not found. Using the first available plan.")
            plan_a = self.app.state.saved_plans[0]
        if not plan_b:
            messagebox.showinfo("Compare", "Plan B not found. Using Plan A for both sides.")
            plan_b = plan_a

        self._fill_compare_tree(self.left_frame._tree, plan_a)   # type: ignore
        self._fill_compare_tree(self.right_frame._tree, plan_b)  # type: ignore
        self.app.status(f"Loaded plans into Compare: A='{plan_a.name}' vs B='{plan_b.name}'")

    def _fill_compare_tree(self, tree: ttk.Treeview, plan: Optional[Plan]) -> None:
        """Populate a compare tree with key/value rows from a Plan's filters."""
        for iid in tree.get_children():
            tree.delete(iid)
        if plan is None:
            tree.insert("", tk.END, values=("No plan", "—"))
            return
        # Human-friendly order where possible
        order = ["budget", "min_downlink", "visa_free_only", "region", "depart_month", "duration_weeks"]
        shown = set()
        for k in order:
            if k in plan.filters:
                tree.insert("", tk.END, values=(k, plan.filters.get(k)))
                shown.add(k)
        for k, v in plan.filters.items():
            if k not in shown:
                tree.insert("", tk.END, values=(k, v))


# =============================================================================
# Page: Settings
# =============================================================================

class SettingsPage(ttk.Frame):
    def __init__(self, parent, app: NomadUI):
        super().__init__(parent)
        self.app = app

        wrap = ttk.Labelframe(self, text="Preferences", padding=12)
        wrap.pack(side=tk.TOP, fill=tk.X, padx=18, pady=18)

        self.var_theme = tk.StringVar(value=self.app.state.theme)
        self.var_region = tk.StringVar(value=self.app.state.default_region)

        ttk.Label(wrap, text="Theme").grid(row=0, column=0, sticky="w")
        ttk.Combobox(wrap, textvariable=self.var_theme, values=["light", "dark", "blue"], width=14).grid(
            row=1, column=0, sticky="w"
        )

        ttk.Label(wrap, text="Default Region").grid(row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Combobox(
            wrap,
            textvariable=self.var_region,
            values=["Global", "Europe", "Asia", "Americas", "Africa", "Oceania"],
            width=16,
        ).grid(row=1, column=1, sticky="w", padx=(18, 0))

        btns = ttk.Frame(self); btns.pack(side=tk.TOP, fill=tk.X, padx=18)
        ttk.Button(btns, text="Apply", command=self.apply).pack(side=tk.LEFT)
        ttk.Button(btns, text="Revert", command=self.revert).pack(side=tk.LEFT, padx=(8, 0))

    def apply(self) -> None:
        self.app.state.theme = self.var_theme.get()
        self.app.state.default_region = self.var_region.get()
        self.app._apply_theme()
        self.app.status("Settings applied.")
        messagebox.showinfo("Settings", "Preferences applied.")

    def revert(self) -> None:
        self.var_theme.set(self.app.state.theme)
        self.var_region.set(self.app.state.default_region)
        self.app.status("Settings reverted.")


# =============================================================================
# Simple text input dialog (modal)
# =============================================================================

class PromptWindow(tk.Toplevel):
    def __init__(self, parent, title: str, prompt: str, initial: str = ""):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        ttk.Label(self, text=prompt).pack(padx=12, pady=(12, 6))
        self.var = tk.StringVar(value=initial)
        entry = ttk.Entry(self, textvariable=self.var, width=40)
        entry.pack(padx=12)
        entry.focus_set(); entry.select_range(0, tk.END)

        btns = ttk.Frame(self); btns.pack(padx=12, pady=12)
        ttk.Button(btns, text="OK", command=self._ok).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=(6, 0))

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())

        self.transient(parent); self.grab_set(); self.wait_window(self)

    def _ok(self) -> None:
        self.result = self.var.get()
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def simple_prompt(parent, title: str, prompt: str, initial: str = "") -> Optional[str]:
    dlg = PromptWindow(parent, title=title, prompt=prompt, initial=initial)
    return dlg.result


# =============================================================================
# Main entry
# =============================================================================

app = NomadUI()
app.mainloop()