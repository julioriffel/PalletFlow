import random
import tkinter as tk
import time
from typing import List, Tuple, Literal, Dict, Optional

# Types for clarity
State = Literal['vazio', 'A', 'B', 'C']
CellData = Tuple[State, int]  # (state, lote_number)
GridData = List[List[CellData]]  # 12 rows x 22 cols

# -------- Simulation Data Structures --------
class Pallet:
    def __init__(self, origin: State, t_prod_min: int, lot_id: int, maturation_minutes: int):
        self.origin: State = origin
        self.t_prod: int = t_prod_min
        self.t_mature: int = t_prod_min + maturation_minutes
        self.lot_id: int = lot_id

    def is_mature(self, now_min: int) -> bool:
        return now_min >= self.t_mature


class SimulationEngine:
    ROWS = 12
    COLS = 22

    def __init__(self, X_minutes: int = 24, maturation_hours: int = 20, window_hours: int = 12, seed: int = 42):
        # Parameters
        self.X = max(1, int(X_minutes))
        self.maturation_minutes = int(maturation_hours * 60)
        self.window_minutes = int(window_hours * 60)
        self.random = random.Random(seed)

        # Time (minutes since start)
        self.now: int = 0

        # Event log to communicate with UI
        self.events: List[Dict] = []

        # Belts: 12 lists (FIFO, head at index 0)
        self.belts: List[List[Pallet]] = [[] for _ in range(self.ROWS)]
        self.capacity_per_belt = self.COLS

        # Origin to belts mapping: A→rows 0-3, B→4-7, C→8-11
        self.origin_rows = {
            'A': list(range(0, 4)),
            'B': list(range(4, 8)),
            'C': list(range(8, 12)),
        }

        # Production scheduling
        self.activation_time = {'A': 0, 'B': self.window_minutes, 'C': 2 * self.window_minutes}
        self.next_prod_time = {'A': self.activation_time['A'],
                               'B': self.activation_time['B'],
                               'C': self.activation_time['C']}

        # Lot management with global sequential lots (no per-type segregation)
        # Initialize first three lots for A, B, C respectively: A1, B2, C3, then 4,5,6... globally.
        self.current_lot_id = {'A': 1, 'B': 2, 'C': 3}
        self.global_next_lot_id = 4
        self.current_lot_remaining = {}
        self.lot_size = max(1, int(2160 // self.X))  # pallets per 12h at rate X/3 min
        for o in ['A', 'B', 'C']:
            self.current_lot_remaining[o] = self.lot_size

        # Phase 2 consumption scheduling
        self.rotation = ['A', 'B', 'C']
        self.rotation_idx = 0
        self.active_origin: Optional[State] = None
        self.window_end_time: int = 0
        self.next_consume_time: int = 0

    @property
    def consumption_tick(self) -> float:
        # One pallet every X/3 minutes (allow fractional minutes)
        return self.X / 3.0

    # ---- Core step ----
    def step(self, dt_minutes: int) -> None:
        # Advance in 1-minute resolution to handle multiple events robustly
        steps = max(1, int(dt_minutes))
        for _ in range(steps):
            self._maybe_start_window()
            self._try_consume()
            self._try_produce()
            self.now += 1

    # ---- Phase 1: Production ----
    def _try_produce(self) -> None:
        for origin in ['A', 'B', 'C']:
            if self.now < self.activation_time[origin]:
                continue
            # Attempt in a while loop if multiple productions scheduled at same minute
            while self.now >= self.next_prod_time[origin]:
                target_row = self._select_belt_for_origin(origin)
                if target_row is None:
                    # Blocked; try again next minute (do not advance next_prod_time)
                    break
                # Assign lot at creation time
                lot_id = self._assign_lot(origin)
                pallet = Pallet(origin, self.now, lot_id, self.maturation_minutes)
                self.belts[target_row].append(pallet)
                self.next_prod_time[origin] += self.X

    def _select_belt_for_origin(self, origin: State) -> Optional[int]:
        rows = self.origin_rows[origin]
        # Choose the belt with most free space; tie-break by earliest row index
        best_row = None
        best_free = -1
        for r in rows:
            free = self.capacity_per_belt - len(self.belts[r])
            if free > best_free:
                best_free = free
                best_row = r
        if best_free <= 0:
            return None
        return best_row

    def _assign_lot(self, origin: State) -> int:
        # If the current lot for this origin is exhausted, advance to the next global lot id
        if self.current_lot_remaining[origin] <= 0:
            self.current_lot_id[origin] = self.global_next_lot_id
            self.global_next_lot_id += 1
            self.current_lot_remaining[origin] = self.lot_size
        lot_id = self.current_lot_id[origin]
        self.current_lot_remaining[origin] -= 1
        return lot_id

    # ---- Phase 2: Window scheduler and consumption ----
    def _maybe_start_window(self) -> None:
        if self.active_origin is not None and self.now < self.window_end_time:
            return
        # Window ended or not started; try to start next
        if self.active_origin is not None and self.now >= self.window_end_time:
            # advance rotation
            self.rotation_idx = (self.rotation_idx + 1) % len(self.rotation)
            self.active_origin = None
        origin = self.rotation[self.rotation_idx]
        # Check trigger using two criteria:
        # 1) Enough mature at start: mature_now >= ceil(1440 / X)
        # 2) Enough by end of window: mature_now + maturing_in_window >= lot_size
        start_needed = (1440 + self.X - 1) // self.X  # ceil(1440 / X)
        mature_now = self._count_mature_until(origin, self.now)
        maturing_in_window = self._count_maturing_in_window(origin, self.now, self.now + self.window_minutes)
        total_ready_by_end = mature_now + maturing_in_window
        if mature_now >= start_needed and total_ready_by_end >= self.lot_size:
            self.active_origin = origin
            self.window_end_time = self.now + self.window_minutes
            self.next_consume_time = self.now  # start immediately
            # Emit event for UI logging
            self.events.append({
                'type': 'window_start',
                'origin': origin,
                'time': self.now,
                'lot_size': self.lot_size
            })
        else:
            # Not enough; keep waiting (do nothing this minute)
            pass

    def _count_ready_by_end(self, origin: State, end_time: int) -> int:
        cnt = 0
        for r in self.origin_rows[origin]:
            for p in self.belts[r]:
                if p.t_mature <= end_time:
                    cnt += 1
        return cnt

    def _count_mature_until(self, origin: State, t: int) -> int:
        """Count pallets of origin with t_mature <= t."""
        cnt = 0
        for r in self.origin_rows[origin]:
            for p in self.belts[r]:
                if p.t_mature <= t:
                    cnt += 1
        return cnt

    def _count_maturing_in_window(self, origin: State, start: int, end: int) -> int:
        """Count pallets of origin that mature in (start, end] interval."""
        cnt = 0
        for r in self.origin_rows[origin]:
            for p in self.belts[r]:
                if start < p.t_mature <= end:
                    cnt += 1
        return cnt

    def _try_consume(self) -> None:
        if self.active_origin is None:
            return
        if self.now < self.next_consume_time or self.now > self.window_end_time:
            return
        # Try to pop one pallet from prioritized belts (first 3)
        origin = self.active_origin
        popped = self._pop_mature_from_prioritized(origin)
        if popped:
            self.next_consume_time += self.consumption_tick
        else:
            # If cannot consume now (no mature at heads), just wait to next minute
            # Do not advance next_consume_time; we'll try again next minute
            pass

    def _pop_mature_from_prioritized(self, origin: State) -> bool:
        rows = self.origin_rows[origin]
        prioritized = rows[:3]
        others = rows[3:]
        # First check prioritized belts
        for r in prioritized:
            if self._pop_if_mature_head(r):
                return True
        # Fallback: try other belts of the same origin
        for r in others:
            if self._pop_if_mature_head(r):
                return True
        return False

    def _pop_if_mature_head(self, row: int) -> bool:
        if not self.belts[row]:
            return False
        head = self.belts[row][0]
        if head.is_mature(self.now):
            self.belts[row].pop(0)
            return True
        return False

    # ---- View helper ----
    def grid_as_cells(self) -> GridData:
        grid: GridData = [[('vazio', 0) for _ in range(self.COLS)] for _ in range(self.ROWS)]
        for r in range(self.ROWS):
            belt = self.belts[r]
            # Visual layout: head (consumption side) at rightmost column, tail/insertion at left.
            # belts[r][0] is head (to be consumed first), belts[r][-1] is newest inserted (leftmost).
            n = min(len(belt), self.COLS)
            for idx in range(n):
                p = belt[idx]
                # Map logical index idx (0=head) to column c where c=COLS-1-idx so head is at right side.
                c = self.COLS - 1 - idx
                grid[r][c] = (p.origin, p.lot_id)
        return grid

    def drain_events(self) -> List[Dict]:
        ev = self.events
        self.events = []
        return ev


class HeatmapApp(tk.Tk):
    """
    Tkinter application that renders a 12x22 heatmap of conveyor belts (esteiras).

    - Each cell shows a color mapped to the state: vazio/A/B/C
    - Each cell shows a centered number indicating the lote in which the pallet will be consumed

    Usage:
        app = HeatmapApp()
        app.update_grid(grid_data)  # grid_data shape (12 x 22), entries (state, lote)
        app.mainloop()

    Where state in {'vazio', 'A', 'B', 'C'} and lote is an int.
    """

    ROWS = 12
    COLS = 22

    def __init__(self, cell_size: int = 40):
        super().__init__()
        self.title("Heatmap de Esteiras (12x22)")
        self.resizable(False, False)

        self.cell_size = cell_size
        width = self.COLS * self.cell_size
        height = self.ROWS * self.cell_size

        # Top summary frame (counters)
        self.summary_frame = tk.Frame(self, bg="#fafafa")
        self.summary_frame.pack(side=tk.TOP, fill=tk.X)

        # Suggested column labels
        self.header_labels = ["Tipo", "Total de itens", "Maduros", "Em maturação"]
        self.types = ["A", "B", "C", "Total"]

        # Create header row
        for j, text in enumerate(self.header_labels):
            lbl = tk.Label(self.summary_frame, text=text, font=("Arial", 11, "bold"), bg="#fafafa")
            lbl.grid(row=0, column=j, padx=6, pady=(6, 2), sticky="w")

        # Storage for dynamic value labels
        self.counter_labels: Dict[str, Dict[str, tk.Label]] = {}

        for i, t in enumerate(self.types, start=1):
            # First column: type label
            tlbl = tk.Label(self.summary_frame, text=t, font=("Arial", 11), bg="#fafafa")
            tlbl.grid(row=i, column=0, padx=6, pady=2, sticky="w")
            # Value columns placeholders
            row_labels: Dict[str, tk.Label] = {}
            for j, key in enumerate(["total", "maduros", "maturacao"], start=1):
                vlbl = tk.Label(self.summary_frame, text="0", font=("Arial", 11), bg="#fafafa")
                vlbl.grid(row=i, column=j, padx=6, pady=2, sticky="w")
                row_labels[key] = vlbl
            self.counter_labels[t] = row_labels

        # Maturity rule (assumption): lote <= threshold => maduro; else em maturação
        self.maturity_threshold: int = 50

        # Controls frame (inputs, buttons, speed, timer)
        self.controls_frame = tk.Frame(self, bg="#f0f0f0", padx=6, pady=4)
        self.controls_frame.pack(side=tk.TOP, fill=tk.X)

        # X input (integer)
        tk.Label(self.controls_frame, text="X:", bg="#f0f0f0").pack(side=tk.LEFT)
        self.x_var = tk.StringVar(value="24")
        vcmd = (self.register(self._validate_int), "%P")
        self.x_entry = tk.Entry(self.controls_frame, width=6, textvariable=self.x_var,
                                 validate="key", validatecommand=vcmd)
        self.x_entry.pack(side=tk.LEFT, padx=(2, 10))

        # Control buttons
        self.start_btn = tk.Button(self.controls_frame, text="Iniciar", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=2)
        self.pause_btn = tk.Button(self.controls_frame, text="Pausar", command=self.pause)
        self.pause_btn.pack(side=tk.LEFT, padx=2)
        self.reset_btn = tk.Button(self.controls_frame, text="Reiniciar", command=self.restart)
        self.reset_btn.pack(side=tk.LEFT, padx=2)

        # Speed buttons
        tk.Label(self.controls_frame, text="Velocidade:", bg="#f0f0f0").pack(side=tk.LEFT, padx=(10, 2))
        self.speed_values = [1, 2, 4, 8, 16, 32]
        self.speed = 1
        self.speed_buttons: Dict[int, tk.Button] = {}
        for val in self.speed_values:
            btn = tk.Button(self.controls_frame, text=f"{val}x", command=lambda v=val: self.set_speed(v))
            btn.pack(side=tk.LEFT, padx=1)
            self.speed_buttons[val] = btn
        # Timer label
        self.timer_label = tk.Label(self.controls_frame, text="0d 00:00", font=("Arial", 11, "bold"), bg="#f0f0f0")
        self.timer_label.pack(side=tk.RIGHT)

        # Runtime state for scheduling
        self.running: bool = False
        self._cycle_after_id: Optional[str] = None
        self._timer_after_id: Optional[str] = None
        self._start_monotonic: float = 0.0  # kept for compatibility (unused for simulated time)
        self._elapsed_accum: float = 0.0    # kept for compatibility (unused for simulated time)
        self._sim_minutes_accum: float = 0.0    # simulated minutes accumulated based on X and speed
        self._last_timer_monotonic: float = 0.0 # timestamp of the last timer update

        # Simulation engine instance (created on start)
        self.engine: Optional[SimulationEngine] = None

        # Highlight default speed
        self._update_speed_buttons()

        # Cleanup on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Center area: left = canvas, right = log panel
        self.center_frame = tk.Frame(self)
        self.center_frame.pack(fill=tk.BOTH, expand=True)

        # Canvas for heatmap (left)
        self.canvas = tk.Canvas(self.center_frame, width=width, height=height, highlightthickness=0, bg="#ffffff")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Build right-side log panel
        self._build_log_panel(height)

        # Define colors for states
        self.colors = {
            'vazio': '#E0E0E0',  # light gray
            'A': '#4FC3F7',      # light blue
            'B': '#81C784',      # light green
            'C': '#FFB74D',      # orange
        }

        # Prepare storage for rect and text item ids for quick updates
        self.rect_items: List[List[int]] = [[0 for _ in range(self.COLS)] for _ in range(self.ROWS)]
        self.text_items: List[List[int]] = [[0 for _ in range(self.COLS)] for _ in range(self.ROWS)]

        # Initialize default grid with vazio and lote 0
        initial_grid: GridData = [[('vazio', 0) for _ in range(self.COLS)] for _ in range(self.ROWS)]
        self._draw_grid(initial_grid)
        self._update_counters(initial_grid)
        
        # Initialize log panel content
        self._append_log("Aplicação inicializada. Aguarde o início de um lote para registrar o status.")

    def _draw_grid(self, grid: GridData) -> None:
        """Draws the full grid from scratch and stores canvas item ids for future updates."""
        self.canvas.delete("all")
        for r in range(self.ROWS):
            for c in range(self.COLS):
                x0 = c * self.cell_size
                y0 = r * self.cell_size
                x1 = x0 + self.cell_size
                y1 = y0 + self.cell_size

                state, lote = grid[r][c]
                fill_color = self.colors.get(state, self.colors['vazio'])

                rect_id = self.canvas.create_rectangle(
                    x0, y0, x1, y1,
                    fill=fill_color,
                    outline="#9E9E9E",
                    width=1
                )

                # Centered text for lote number
                cx = (x0 + x1) // 2
                cy = (y0 + y1) // 2
                text_color = "#000000" if state != 'C' else "#000000"  # keep black for readability
                text_id = self.canvas.create_text(
                    cx, cy,
                    text=str(lote),
                    fill=text_color,
                    font=("Arial", max(10, self.cell_size // 3), "bold")
                )

                self.rect_items[r][c] = rect_id
                self.text_items[r][c] = text_id

    def update_grid(self, grid: GridData) -> None:
        """
        Update the grid cells' colors and lote numbers.
        Expects grid to be size 12x22 of tuples (state, lote).
        Also refreshes the summary counters at the top.
        """
        if len(grid) != self.ROWS or any(len(row) != self.COLS for row in grid):
            raise ValueError(f"Grid must be {self.ROWS}x{self.COLS}")

        for r in range(self.ROWS):
            for c in range(self.COLS):
                state, lote = grid[r][c]
                fill_color = self.colors.get(state, self.colors['vazio'])

                rect_id = self.rect_items[r][c]
                text_id = self.text_items[r][c]

                # Update rectangle fill
                self.canvas.itemconfigure(rect_id, fill=fill_color)
                # Update text
                self.canvas.itemconfigure(text_id, text=str(lote))

        # Update summary counters
        self._update_counters(grid)

        # Ensure canvas updates visually
        self.canvas.update_idletasks()

    def _update_counters(self, grid: GridData) -> None:
        """Compute and display counters per type (A, B, C) and totals.

        Prefer accurate maturity based on SimulationEngine (20h since creation) when available.
        Fallback: if engine is None, estimate using the grid and a threshold on lote numbers.
        """
        counters: Dict[str, Dict[str, int]] = {t: {"total": 0, "maduros": 0, "maturacao": 0} for t in ["A", "B", "C"]}

        if self.engine is not None:
            now_min = self.engine.now
            # Count items directly from belts to respect real pallets and their maturity
            for origin in ["A", "B", "C"]:
                for row in self.engine.origin_rows[origin]:
                    for p in self.engine.belts[row]:
                        counters[p.origin]["total"] += 1
                        if p.is_mature(now_min):
                            counters[p.origin]["maduros"] += 1
                        else:
                            counters[p.origin]["maturacao"] += 1
        else:
            # Fallback heuristic from grid (used only in demo mode without engine)
            for r in range(self.ROWS):
                for c in range(self.COLS):
                    state, lote = grid[r][c]
                    if state in counters:
                        counters[state]["total"] += 1
                        if lote <= self.maturity_threshold:
                            counters[state]["maduros"] += 1
                        else:
                            counters[state]["maturacao"] += 1

        # Compute totals across types
        totals = {"total": 0, "maduros": 0, "maturacao": 0}
        for t in ["A", "B", "C"]:
            for k in totals.keys():
                totals[k] += counters[t][k]

        # Update labels for A, B, C
        for t in ["A", "B", "C"]:
            self.counter_labels[t]["total"].configure(text=str(counters[t]["total"]))
            self.counter_labels[t]["maduros"].configure(text=str(counters[t]["maduros"]))
            self.counter_labels[t]["maturacao"].configure(text=str(counters[t]["maturacao"]))

        # Update total row
        self.counter_labels["Total"]["total"].configure(text=str(totals["total"]))
        self.counter_labels["Total"]["maduros"].configure(text=str(totals["maduros"]))
        self.counter_labels["Total"]["maturacao"].configure(text=str(totals["maturacao"]))

    # ----- Log panel & event handling -----
    def _build_log_panel(self, height: int) -> None:
        self.log_frame = tk.Frame(self.center_frame, bg="#f7f7f7")
        self.log_frame.pack(side=tk.RIGHT, fill=tk.Y)
        title = tk.Label(self.log_frame, text="Log de Lotes", font=("Arial", 11, "bold"), bg="#f7f7f7")
        title.pack(side=tk.TOP, anchor="w", padx=6, pady=(6, 2))
        self.log_text = tk.Text(self.log_frame, width=40, height=max(10, height // 20), wrap=tk.WORD, state=tk.DISABLED, bg="#fcfcfc")
        # Enable text selection and copying with standard shortcuts even when disabled
        # Allow selecting text by mouse drag, and copying via Ctrl+C or context menu
        # Bind Ctrl+C and Command+C (macOS) to copy selection
        self.log_text.bind("<Control-c>", lambda e: self._copy_log_selection())
        self.log_text.bind("<Command-c>", lambda e: self._copy_log_selection())
        self.log_text.bind("<Control-a>", lambda e: (self.log_text.tag_add("sel", "1.0", "end-1c"), "break"))
        self.log_text.bind("<Command-a>", lambda e: (self.log_text.tag_add("sel", "1.0", "end-1c"), "break"))
        # Context menu (right-click)
        self.log_menu = tk.Menu(self.log_frame, tearoff=0)
        self.log_menu.add_command(label="Copiar", command=self._copy_log_selection)
        self.log_menu.add_command(label="Copiar tudo", command=self._copy_all_logs)
        self.log_text.bind("<Button-3>", self._show_log_context_menu)
        self.log_text.bind("<Control-Button-1>", self._show_log_context_menu)

        self.log_scroll = tk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(6, 0), pady=(0, 6))
        self.log_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 6))

    def _append_log(self, text: str) -> None:
        if not hasattr(self, 'log_text'):
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        # Keep selection visible even when disabled
        try:
            self.log_text.configure(inactiveselectbackground=self.log_text.cget('selectbackground'))
        except Exception:
            pass

    def _clear_logs(self) -> None:
        if not hasattr(self, 'log_text'):
            return
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.configure(state=tk.DISABLED)
        try:
            self.log_text.configure(inactiveselectbackground=self.log_text.cget('selectbackground'))
        except Exception:
            pass

    # ----- Log copy helpers -----
    def _copy_log_selection(self) -> None:
        try:
            sel_start = self.log_text.index("sel.first")
            sel_end = self.log_text.index("sel.last")
        except Exception:
            return  # No selection
        try:
            text = self.log_text.get(sel_start, sel_end)
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def _copy_all_logs(self) -> None:
        try:
            # Exclude trailing newline
            text = self.log_text.get("1.0", "end-1c")
            if not text:
                return
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def _show_log_context_menu(self, event) -> None:
        try:
            # Enable/disable 'Copiar' based on selection presence
            has_sel = True
            try:
                _ = self.log_text.index("sel.first")
                _ = self.log_text.index("sel.last")
            except Exception:
                has_sel = False
            if has_sel:
                self.log_menu.entryconfig(0, state=tk.NORMAL)
            else:
                self.log_menu.entryconfig(0, state=tk.DISABLED)
            self.log_menu.tk.call("tk_popup", self.log_menu, event.x_root, event.y_root)
        except Exception:
            pass

    def _snapshot_status(self, at_minute: int) -> Dict[str, Dict[str, int]]:
        counters: Dict[str, Dict[str, int]] = {t: {"total": 0, "maduros": 0, "maturacao": 0} for t in ["A", "B", "C"]}
        if self.engine is None:
            return counters
        for origin in ["A", "B", "C"]:
            for row in self.engine.origin_rows[origin]:
                for p in self.engine.belts[row]:
                    counters[p.origin]["total"] += 1
                    if p.is_mature(at_minute):
                        counters[p.origin]["maduros"] += 1
                    else:
                        counters[p.origin]["maturacao"] += 1
        return counters

    def _process_engine_events(self) -> None:
        if self.engine is None:
            return
        events = self.engine.drain_events()
        if not events:
            return
        for ev in events:
            if ev.get('type') == 'window_start':
                t = ev.get('time', self.engine.now)
                origin = ev.get('origin', '?')
                lot_size = ev.get('lot_size', 0)
                time_str = self._format_minutes(t)
                snap = self._snapshot_status(t)
                def fmt(o: str) -> str:
                    c = snap[o]
                    return f"{o} T={c['total']} M={c['maduros']} EmM={c['maturacao']}"
                line = f"[{time_str}] Início de lote {origin} (tamanho={lot_size}). Status: " \
                       f"{fmt('A')} | {fmt('B')} | {fmt('C')}"
                self._append_log(line)

    # ----- Controls & Scheduling -----
    def _validate_int(self, proposed: str) -> bool:
        # Allow empty string during editing; treat as 0 when used
        if proposed == "":
            return True
        try:
            int(proposed)
            return True
        except ValueError:
            return False

    def _update_speed_buttons(self) -> None:
        for val, btn in self.speed_buttons.items():
            if val == self.speed:
                btn.configure(relief=tk.SUNKEN, state=tk.DISABLED)
            else:
                btn.configure(relief=tk.RAISED, state=tk.NORMAL)

    def _get_X(self) -> int:
        try:
            raw = self.x_var.get()
            if raw is None or raw.strip() == "":
                return 24
            val = int(raw)
            return max(1, val)
        except Exception:
            return 24

    def set_speed(self, value: int) -> None:
        if value <= 0:
            value = 1
        self.speed = value
        self._update_speed_buttons()
        # Reschedule cycle with new speed if running
        if self.running:
            if self._cycle_after_id is not None:
                try:
                    self.after_cancel(self._cycle_after_id)
                except Exception:
                    pass
                self._cycle_after_id = None
            self._schedule_cycle()

    def start(self) -> None:
        if not self.running:
            # Initialize simulation engine if needed (reads X)
            if self.engine is None:
                X = self._get_X()
                self.engine = SimulationEngine(X_minutes=X)
            self.running = True
            # Initialize timer reference for simulated time
            self._last_timer_monotonic = time.monotonic()
            self._schedule_cycle()
            self._schedule_timer()

    def pause(self) -> None:
        if self.running:
            # Finalize accumulation up to now
            self._update_timer()
            self.running = False
            # Cancel scheduled callbacks
            if self._cycle_after_id is not None:
                try:
                    self.after_cancel(self._cycle_after_id)
                except Exception:
                    pass
                self._cycle_after_id = None
            if self._timer_after_id is not None:
                try:
                    self.after_cancel(self._timer_after_id)
                except Exception:
                    pass
                self._timer_after_id = None
            # Update timer label once with current simulated time (engine timeline if available)
            if self.engine is not None:
                self.timer_label.configure(text=self._format_minutes(self.engine.now))
            else:
                self.timer_label.configure(text=self._format_minutes(self._sim_minutes_accum))

    def restart(self) -> None:
        # Reset simulated time and stop then start fresh
        self.pause()
        self._sim_minutes_accum = 0.0
        self.timer_label.configure(text=self._format_minutes(0.0))
        # Reset simulation engine (new X may apply)
        self.engine = None
        # Reset the grid to vazio
        initial_grid: GridData = [[('vazio', 0) for _ in range(self.COLS)] for _ in range(self.ROWS)]
        self.update_grid(initial_grid)
        # Clear logs as part of restart
        self._clear_logs()
        # Não iniciar automaticamente após reiniciar; o usuário deve clicar em Iniciar
        # (deixe o estado parado)

    def _schedule_cycle(self) -> None:
        if not self.running:
            return
        # Interval in ms based on speed (cycles per second)
        interval_ms = max(1, int(1000 / max(1, self.speed)))
        self._cycle_after_id = self.after(interval_ms, self._cycle_once)

    def _cycle_once(self) -> None:
        if not self.running:
            return
        if self.engine is None:
            X = self._get_X()
            self.engine = SimulationEngine(X_minutes=X)
        # Advance simulation by one consumption tick in minutes
        self.engine.step(self.engine.consumption_tick)
        self.update_grid(self.engine.grid_as_cells())
        # Process any engine events (e.g., new lot start) and append logs
        self._process_engine_events()
        # Continue scheduling next cycle
        self._schedule_cycle()

    def _schedule_timer(self) -> None:
        # Update timer roughly every second; compute simulated minutes based on X and speed
        if not self.running:
            return
        self._update_timer()
        self._timer_after_id = self.after(1000, self._schedule_timer)

    def _update_timer(self) -> None:
        if not self.running:
            return
        # Display the simulation's relative time based on engine.now minutes for consistency
        if self.engine is not None:
            minutes = self.engine.now
            self.timer_label.configure(text=self._format_minutes(minutes))
            return
        # Fallback: if engine not created yet, keep previous accumulation behavior
        now = time.monotonic()
        if self._last_timer_monotonic == 0.0:
            self._last_timer_monotonic = now
        delta_sec = max(0.0, now - self._last_timer_monotonic)
        self._last_timer_monotonic = now
        X = self._get_X()
        self._sim_minutes_accum += delta_sec * X * max(1, self.speed)
        self.timer_label.configure(text=self._format_minutes(self._sim_minutes_accum))

    def _format_minutes(self, total_minutes_float: float) -> str:
        total_minutes = int(total_minutes_float)
        days = total_minutes // (24 * 60)
        hours = (total_minutes % (24 * 60)) // 60
        minutes = total_minutes % 60
        return f"{days}d {hours:02d}:{minutes:02d}"

    def _on_close(self) -> None:
        # Ensure callbacks are cancelled
        try:
            if self._cycle_after_id is not None:
                self.after_cancel(self._cycle_after_id)
        except Exception:
            pass
        try:
            if self._timer_after_id is not None:
                self.after_cancel(self._timer_after_id)
        except Exception:
            pass
        self.destroy()


def demo_data(rows: int = 12, cols: int = 22) -> GridData:
    """Generate demo data with random states and lote numbers for visualization."""
    states: List[State] = ['vazio', 'A', 'B', 'C']
    data: GridData = []
    for _ in range(rows):
        row: List[CellData] = []
        for _ in range(cols):
            st = random.choice(states)
            lote = 0 if st == 'vazio' else random.randint(1, 99)
            row.append((st, lote))
        data.append(row)
    return data


if __name__ == "__main__":
    # Simple demo: press the window to refresh with new random data
    app = HeatmapApp(cell_size=40)
    app.update_grid(demo_data())
    # Não iniciar automaticamente: aguarda o usuário clicar em Iniciar
    # (mantemos o bloco try/except anterior removido, pois não há chamada de start aqui)

    def refresh(_event=None):
        app.update_grid(demo_data())

    app.bind("<Button-1>", refresh)
    app.mainloop()
