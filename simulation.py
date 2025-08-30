import random
from typing import List, Tuple, Literal, Dict, Optional, Any, Protocol

# Public types
State = Literal['vazio', 'A', 'B', 'C']
CellData = Tuple[State, int]
GridData = List[List[CellData]]


# ---- Strategy Interfaces ----
class AllocationStrategy(Protocol):
    def select_belt(self, engine: 'SimulationEngine', origin: State) -> Optional[int]:
        ...


class ConsumptionStrategy(Protocol):
    def consume(self, engine: 'SimulationEngine', origin: State) -> bool:
        """Consume exactly one pallet if possible for the given origin; return True if consumed."""
        ...


# ---- Default and extra strategies ----
class MostFreeAllocation:
    """Pick the belt within origin rows with the most free space; tie-break by lowest row index."""
    def select_belt(self, engine: 'SimulationEngine', origin: State) -> Optional[int]:
        rows = engine.origin_rows[origin]
        best_row = None
        best_free = -1
        for r in rows:
            free = engine.capacity_per_belt - len(engine.belts[r])
            if free > best_free:
                best_free = free
                best_row = r
        if best_free <= 0:
            return None
        return best_row


class RoundRobinAllocation:
    """Cycle through origin rows round-robin, picking the next row with free space."""
    def __init__(self):
        self._next_index: Dict[State, int] = {'A': 0, 'B': 0, 'C': 0}

    def select_belt(self, engine: 'SimulationEngine', origin: State) -> Optional[int]:
        rows = engine.origin_rows[origin]
        n = len(rows)
        start = self._next_index[origin] % n
        for k in range(n):
            idx = (start + k) % n
            r = rows[idx]
            if len(engine.belts[r]) < engine.capacity_per_belt:
                self._next_index[origin] = (idx + 1) % n
                return r
        return None


class PrioritizedFirstThreeConsumption:
    """Try first three belts of origin, then the remaining, consuming mature heads only."""
    def consume(self, engine: 'SimulationEngine', origin: State) -> bool:
        rows = engine.origin_rows[origin]
        prioritized = rows[:3]
        others = rows[3:]
        for r in prioritized:
            if engine.pop_if_mature_head(r):
                return True
        for r in others:
            if engine.pop_if_mature_head(r):
                return True
        return False


class LongestQueueHeadConsumption:
    """Pick the belt with the longest queue having a mature head; fallback scanning."""
    def consume(self, engine: 'SimulationEngine', origin: State) -> bool:
        rows = engine.origin_rows[origin]
        # Find rows with mature head
        candidate_rows: List[int] = []
        for r in rows:
            if engine.belts[r] and engine.belts[r][0].is_mature(engine.now):
                candidate_rows.append(r)
        if candidate_rows:
            # Choose the one with the largest queue length
            best_row = max(candidate_rows, key=lambda rr: len(engine.belts[rr]))
            return engine.pop_if_mature_head(best_row)
        # Fallback: scan any row for mature head
        for r in rows:
            if engine.pop_if_mature_head(r):
                return True
        return False


# Registries for GUI usage
ALLOCATION_STRATEGIES: Dict[str, Any] = {
    'Mais espaço livre': MostFreeAllocation,
    'Round-robin por esteira': RoundRobinAllocation,
}

CONSUMPTION_STRATEGIES: Dict[str, Any] = {
    'Priorizar 3 primeiras': PrioritizedFirstThreeConsumption,
    'Cabeça mais longa': LongestQueueHeadConsumption,
}


class Pallet:
    def __init__(self, origin: State, t_prod_min: int, lot_id: int, maturation_minutes: int, pallet_id: int):
        self.origin: State = origin
        self.t_prod: int = t_prod_min
        self.t_mature: int = t_prod_min + maturation_minutes
        self.lot_id: int = lot_id
        self.pallet_id: int = pallet_id

    def is_mature(self, now_min: int) -> bool:
        return now_min >= self.t_mature


class SimulationEngine:
    ROWS = 12
    COLS = 22

    def __init__(self, X_minutes: int = 24, maturation_hours: int = 20, window_hours: int = 12, seed: int = 42,
                 allocation_strategy: Optional[AllocationStrategy] = None,
                 consumption_strategy: Optional[ConsumptionStrategy] = None):
        # Parameters
        self.X = max(1, int(X_minutes))
        self.maturation_minutes = int(maturation_hours * 60)
        self.window_minutes = int(window_hours * 60)
        self.random = random.Random(seed)

        # Time (minutes since start)
        self.now: int = 0

        # Event log to communicate with UI
        self.events: List[Dict] = []

        # Per-pallet records for CSV export
        # key: pallet_id -> {'tipo': 'A'|'B'|'C', 'lote': int, 'pallet_id': int, 'criado_min': int, 'consumido_min': Optional[int]}
        self.pallet_records: Dict[int, Dict[str, Any]] = {}
        self.next_pallet_id: int = 1

        # Belts: 12 lists (FIFO, head at index 0)
        self.belts: List[List[Pallet]] = [[] for _ in range(self.ROWS)]
        self.capacity_per_belt = self.COLS

        # Strategy selection (defaults if none provided)
        self.allocation_strategy: AllocationStrategy = allocation_strategy or MostFreeAllocation()
        self.consumption_strategy: ConsumptionStrategy = consumption_strategy or PrioritizedFirstThreeConsumption()

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
                target_row = self.allocation_strategy.select_belt(self, origin)
                if target_row is None:
                    # Blocked; try again next minute (do not advance next_prod_time)
                    break
                # Assign lot at creation time
                lot_id = self._assign_lot(origin)
                pallet_id = self.next_pallet_id
                self.next_pallet_id += 1
                pallet = Pallet(origin, self.now, lot_id, self.maturation_minutes, pallet_id)
                # Record creation for CSV export
                self.pallet_records[pallet_id] = {
                    'tipo': origin,
                    'lote': lot_id,
                    'pallet_id': pallet_id,
                    'criado_min': self.now,
                    'consumido_min': None,
                }
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
        origin = self.active_origin
        popped = self.consumption_strategy.consume(self, origin)
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
            popped = self.belts[row].pop(0)
            # Record consumption time for CSV export
            rec = self.pallet_records.get(popped.pallet_id)
            if rec is not None and rec.get('consumido_min') is None:
                rec['consumido_min'] = self.now
            return True
        return False

    # Public wrapper for strategies
    def pop_if_mature_head(self, row: int) -> bool:
        return self._pop_if_mature_head(row)

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

    def get_pallet_records(self) -> List[Dict[str, Any]]:
        """Return a snapshot list of pallet records for CSV export."""
        # Return as a list to avoid accidental mutation by callers
        return list(self.pallet_records.values())
