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


class DedicatedThreePlusDynamicAllocation:
    """
    Prioritize dynamic belts for allocation with specific mapping:
      - Origin A: prefer dynamic belts 9 and 10 (two belts), then 11; fallback to dedicated if needed.
      - Origin B: prefer dynamic belt 11 (one belt); fallback to dedicated if needed.
      - Origin C: use dedicated belts; fallback to dynamic only if all dedicated are full.
    Maintain lot stickiness within the preferred set: if any preferred belt already contains the next lot and has free space, use it.
    Otherwise, pick the one with most free space within the preferred set; then fallback to dedicated.
    """

    def select_belt(self, engine: 'SimulationEngine', origin: State) -> Optional[int]:
        dedicated = engine.origin_rows[origin]
        capacity = engine.capacity_per_belt

        # Determine preferred dynamic belts per origin according to requirement
        if origin == 'A':
            # Para A: usar 2 esteiras dinâmicas (9 e 10) até completar 44 itens (2x22).
            # Depois disso, começar a inserir nas dedicadas (mantendo regra de não misturar).
            if engine.current_lot_produced['A'] < 44:
                preferred_dynamic: List[int] = [9, 10]
            else:
                preferred_dynamic = []
        elif origin == 'B':
            preferred_dynamic = [11]
        else:  # 'C' or others
            preferred_dynamic = []

        # Infer next lot id without mutating engine state (for stickiness)
        next_lot = engine.peek_next_lot_id(origin)
        if next_lot is None:
            next_lot = engine.current_lot_id[origin]

        # Helper to select most free from a list of rows
        def select_most_free(from_rows: List[int]) -> Optional[int]:
            best_r = None
            best_free = -1
            for r in from_rows:
                free = capacity - len(engine.belts[r])
                if free > best_free:
                    best_free = free
                    best_r = r
            if best_free <= 0:
                return None
            return best_r

        # 1) Try preferred dynamic belts first, keeping lot stickiness
        if preferred_dynamic:
            candidates_same_lot: List[int] = []
            for r in preferred_dynamic:
                belt = engine.belts[r]
                if len(belt) >= capacity:
                    continue
                if any(p.lot_id == next_lot and p.origin == origin for p in belt):
                    candidates_same_lot.append(r)
            if candidates_same_lot:
                best_row = max(candidates_same_lot, key=lambda rr: (capacity - len(engine.belts[rr]), -rr))
                return best_row
            # Otherwise pick the most free among preferred dynamic belts
            pick = select_most_free(preferred_dynamic)
            if pick is not None:
                return pick

        # 2) Fallback to dedicated belts (most free)
        pick = select_most_free(dedicated)
        if pick is not None:
            return pick

        # 3) As a last resort (e.g., for 'C' when dedicated are full), allow any remaining dynamic belts
        remaining_dynamic = [r for r in engine.dynamic_rows if r not in preferred_dynamic]
        return select_most_free(remaining_dynamic)


class PrioritizedFirstThreeConsumption:
    """Try dedicated belts first, then shared dynamic belts; consume only head pallets of the active origin that are mature."""

    def consume(self, engine: 'SimulationEngine', origin: State) -> bool:
        # Dedicated rows for this origin
        for r in engine.origin_rows[origin]:
            if engine.pop_if_mature_head_of_origin(r, origin):
                return True
        # Then try dynamic rows shared across types
        for r in engine.dynamic_rows:
            if engine.pop_if_mature_head_of_origin(r, origin):
                return True
        return False


class LongestQueueHeadConsumption:
    """Pick the belt (dedicated or dynamic) with the longest queue whose head is a mature pallet of the active origin; fallback scanning with origin check."""

    def consume(self, engine: 'SimulationEngine', origin: State) -> bool:
        rows = engine.origin_rows[origin] + engine.dynamic_rows
        # Find rows with mature head of the same origin
        candidate_rows: List[int] = []
        for r in rows:
            if engine.belts[r]:
                head = engine.belts[r][0]
                if head.origin == origin and head.is_mature(engine.now):
                    candidate_rows.append(r)
        if candidate_rows:
            # Choose the one with the largest queue length
            best_row = max(candidate_rows, key=lambda rr: len(engine.belts[rr]))
            return engine.pop_if_mature_head_of_origin(best_row, origin)
        # Fallback: scan any row for mature head of origin
        for r in rows:
            if engine.pop_if_mature_head_of_origin(r, origin):
                return True
        return False


class DynamicLeastFreeSpaceConsumption:
    """Novo algoritmo: consumir prioritariamente das esteiras dinâmicas e sempre daquela com menos espaços vagos.
    Regras:
      - Considerar apenas filas cujo head é do origin ativo e está maduro.
      - Prioridade 1: esteiras dinâmicas (engine.dynamic_rows).
      - Prioridade 2: esteiras dedicadas do origin.
      - Dentro da prioridade, escolher a esteira com MENOS espaços vagos (ou seja, com mais itens na fila).
        Espaços vagos = capacidade - tamanho atual da fila.
      - Empate: menor índice de linha.
    """

    def consume(self, engine: 'SimulationEngine', origin: State) -> bool:
        capacity = engine.capacity_per_belt

        def pick_row(rows: List[int]) -> Optional[int]:
            best_r = None
            best_metric = None  # menor espaços vagos
            for r in rows:
                belt = engine.belts[r]
                if not belt:
                    continue
                head = belt[0]
                if head.origin != origin or not head.is_mature(engine.now):
                    continue
                free = capacity - len(belt)
                metric = (free, r)  # ordenar por menos free, depois por menor índice
                if best_metric is None or metric < best_metric:
                    best_metric = metric
                    best_r = r
            return best_r

        # 1) tentar dinâmicas primeiro
        r = pick_row(engine.dynamic_rows)
        if r is not None:
            return engine.pop_if_mature_head_of_origin(r, origin)
        # 2) depois dedicadas
        r = pick_row(engine.origin_rows[origin])
        if r is not None:
            return engine.pop_if_mature_head_of_origin(r, origin)
        return False


# Registries for GUI usage
ALLOCATION_STRATEGIES: Dict[str, Any] = {
    '3 dedicadas + dinâmico (manter lote)': DedicatedThreePlusDynamicAllocation,
    'Mais espaço livre': MostFreeAllocation,
    'Round-robin por esteira': RoundRobinAllocation,

}

CONSUMPTION_STRATEGIES: Dict[str, Any] = {
    'Dinâmicas com menos espaços vagos (padrão)': DynamicLeastFreeSpaceConsumption,
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
        self.consumption_strategy: ConsumptionStrategy = consumption_strategy or DynamicLeastFreeSpaceConsumption()

        # Origin to belts mapping (dedicated only): A→rows 0-2, B→4-6, C→8-10
        # Global dynamic belts shared across all types: rows 3, 7, 11
        self.origin_rows = {
            'A': [0, 1, 2],
            'B': [3, 4, 5],
            'C': [6, 7, 8],
        }
        self.dynamic_rows: List[int] = [9, 10, 11]
        # Para impedir mistura: consideramos a fila "ocupada" por um lote enquanto o último inserido tiver um lote diferente

        # Production scheduling
        self.activation_time = {'A': 0, 'B': self.window_minutes, 'C': 2 * self.window_minutes}
        self.next_prod_time = {'A': self.activation_time['A'],
                               'B': self.activation_time['B'],
                               'C': self.activation_time['C']}

        # Lot management with global sequential lots (n2160o per-type segregation)
        # Initialize first three lots for A, B, C respectively: A1, B2, C3, then 4,5,6... globally.
        self.current_lot_id = {'A': 1, 'B': 2, 'C': 3}
        self.global_next_lot_id = 4
        # Lot tracking: produced and outstanding counts for current lot per origin
        self.current_lot_produced: Dict[State, int] = {'A': 0, 'B': 0, 'C': 0}
        self.current_lot_outstanding: Dict[State, int] = {'A': 0, 'B': 0, 'C': 0}
        self.lot_size = max(1, int(2160 // self.X))  # pallets per 12h at rate X/3 min

        # Phase 2 consumption scheduling
        self.rotation = ['A', 'B', 'C']
        self.rotation_idx = 0
        self.active_origin: Optional[State] = None
        self.window_end_time: int = 0
        self.next_consume_time: int = 0
        self.window_consumed: int = 0  # pallets consumed in the current window

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
                # Decide lot for next pallet; if None, production must wait until current lot is fully consumed
                lot_id_opt = self._assign_lot(origin)
                if lot_id_opt is None:
                    break
                # Select a belt to place the pallet
                target_row = self.allocation_strategy.select_belt(self, origin)
                if target_row is None:
                    # Blocked; try again next minute (do not advance next_prod_time)
                    break
                # Assign lot at creation time
                lot_id = lot_id_opt
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
                # Regra: não misturar itens na mesma fila: permitir inserir se fila vazia ou último item é do mesmo lote
                belt = self.belts[target_row]
                if belt and belt[-1].lot_id != lot_id:
                    # tentar outra esteira compatível
                    alt_row = self.allocation_strategy.select_belt(self, origin)
                    if alt_row is not None and alt_row != target_row:
                        target_row = alt_row
                        belt = self.belts[target_row]
                # se ainda assim mistura, bloquear produção neste minuto
                if belt and belt[-1].lot_id != lot_id:
                    # não avança next_prod_time; sai do while para tentar depois
                    self.next_pallet_id -= 1
                    # rollback record allocation placeholders
                    del self.pallet_records[pallet_id]
                    return
                self.belts[target_row].append(pallet)
                # Update lot counters
                self.current_lot_produced[origin] += 1
                self.current_lot_outstanding[origin] += 1
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

    def peek_next_lot_id(self, origin: State) -> Optional[int]:
        """Decide which lot id would be used for the next produced pallet of origin.
        Returns None if production must wait (current lot produced quota reached but not fully consumed)."""
        produced = self.current_lot_produced[origin]
        if produced < self.lot_size:
            return self.current_lot_id[origin]
        # produced quota reached; only advance if no outstanding pallets remain
        if self.current_lot_outstanding[origin] > 0:
            return None
        # Can advance to a new lot
        return self.global_next_lot_id

    def _advance_lot(self, origin: State) -> None:
        """Advance current lot for origin to the next global lot and reset counters."""
        self.current_lot_id[origin] = self.global_next_lot_id
        self.global_next_lot_id += 1
        self.current_lot_produced[origin] = 0
        self.current_lot_outstanding[origin] = 0

    def _assign_lot(self, origin: State) -> Optional[int]:
        """Return the lot id to assign for the next pallet of origin, or None if production must wait.
        Regra: não misturar lotes na mesma fila. Só iniciar um novo lote quando o anterior começar a ser consumido,
        e, para A, após completar 2 esteiras (44 itens) deve iniciar nas dedicadas.
        Implementação: só avança de lote se o lote atual já teve ao menos 1 pallet consumido (outstanding < produced),
        ou se produced == 0 (primeiro lote)."""
        # Se já estamos no primeiro pallet do primeiro lote, mantém
        produced = self.current_lot_produced[origin]
        outstanding = self.current_lot_outstanding[origin]
        # Bloqueia avanço de lote até iniciar consumo do atual
        if produced >= self.lot_size and outstanding == produced:
            # lote completo mas nenhum consumido ainda -> aguardar
            return None
        # Política padrão de avanço quando possível
        nxt = self.peek_next_lot_id(origin)
        if nxt is None:
            return None
        if nxt != self.current_lot_id[origin]:
            # Permitir avanço apenas se já houve consumo do lote atual (outstanding < produced)
            if outstanding < produced:
                self._advance_lot(origin)
            else:
                return None
        return self.current_lot_id[origin]

    # ---- Phase 2: Window scheduler and consumption ----
    def _get_current_lot_last_mature(self, origin: State) -> Optional[int]:
        """Return the max t_mature among pallets of the current lot for the given origin, or None if none found."""
        lot_id = self.current_lot_id[origin]
        last = None
        rows = self.origin_rows[origin] + self.dynamic_rows
        for r in rows:
            for p in self.belts[r]:
                if p.origin == origin and p.lot_id == lot_id:
                    if last is None or p.t_mature > last:
                        last = p.t_mature
        return last

    def _is_current_lot_fully_produced_and_unconsumed(self, origin: State) -> bool:
        """Lot must have all pallets produced and none consumed yet (so outstanding == produced == lot_size)."""
        produced = self.current_lot_produced[origin]
        outstanding = self.current_lot_outstanding[origin]
        return produced >= self.lot_size and outstanding == produced

    def _maybe_start_window(self) -> None:
        if self.active_origin is not None and self.now < self.window_end_time:
            return
        # Window ended or not started; try to start next
        if self.active_origin is not None and self.now >= self.window_end_time:
            # advance rotation
            self.rotation_idx = (self.rotation_idx + 1) % len(self.rotation)
            self.active_origin = None
        origin = self.rotation[self.rotation_idx]
        # New rule: start only when 12h remain to the last pallet maturation of the lot
        if not self._is_current_lot_fully_produced_and_unconsumed(origin):
            return
        t_last = self._get_current_lot_last_mature(origin)
        if t_last is None:
            return
        target_start = t_last - self.window_minutes
        if self.now >= target_start:
            self.active_origin = origin
            self.window_end_time = self.now + self.window_minutes
            self.next_consume_time = self.now  # start immediately
            self.window_consumed = 0  # reset consumed counter for this window
            # Emit event for UI logging
            self.events.append({
                'type': 'window_start',
                'origin': origin,
                'time': self.now,
                'lot_size': self.lot_size
            })
        else:
            # Not time yet based on last-mature timing rule; wait
            pass

    def _count_ready_by_end(self, origin: State, end_time: int) -> int:
        cnt = 0
        rows = self.origin_rows[origin] + self.dynamic_rows
        for r in rows:
            for p in self.belts[r]:
                if p.origin == origin and p.t_mature <= end_time:
                    cnt += 1
        return cnt

    def _count_mature_until(self, origin: State, t: int) -> int:
        """Count pallets of origin with t_mature <= t across dedicated and dynamic rows."""
        cnt = 0
        rows = self.origin_rows[origin] + self.dynamic_rows
        for r in rows:
            for p in self.belts[r]:
                if p.origin == origin and p.t_mature <= t:
                    cnt += 1
        return cnt

    def _count_maturing_in_window(self, origin: State, start: int, end: int) -> int:
        """Count pallets of origin that mature in (start, end] interval across dedicated and dynamic rows."""
        cnt = 0
        rows = self.origin_rows[origin] + self.dynamic_rows
        for r in rows:
            for p in self.belts[r]:
                if p.origin == origin and start < p.t_mature <= end:
                    cnt += 1
        return cnt

    def _try_consume(self) -> None:
        if self.active_origin is None:
            return
        if self.now < self.next_consume_time or self.now > self.window_end_time:
            # Last-chance at window boundary: if we're exactly at the end minute and still missing items,
            # try to consume one more pallet ignoring the time spacing. This avoids leaving 1 item behind
            # due to fractional consumption tick rounding.
            if self.active_origin is not None and self.now == self.window_end_time and self.window_consumed < self.lot_size:
                if self.consumption_strategy.consume(self, self.active_origin):
                    self.window_consumed += 1
                    if self.window_consumed >= self.lot_size:
                        self.window_end_time = self.now
            return
        origin = self.active_origin
        popped = self.consumption_strategy.consume(self, origin)
        if popped:
            # track how many consumed in this window
            self.window_consumed += 1
            self.next_consume_time += self.consumption_tick
            # If we've consumed a full lot, close the window immediately
            if self.window_consumed >= self.lot_size:
                # End window now so next minute rotation can proceed
                self.window_end_time = self.now
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
            # Decrement outstanding for the origin's current lot when applicable
            origin = popped.origin
            if popped.lot_id == self.current_lot_id[origin] and self.current_lot_outstanding[origin] > 0:
                self.current_lot_outstanding[origin] -= 1
            return True
        return False

    # Public wrappers for strategies
    def pop_if_mature_head(self, row: int) -> bool:
        return self._pop_if_mature_head(row)

    def pop_if_mature_head_of_origin(self, row: int, origin: State) -> bool:
        if not self.belts[row]:
            return False
        head = self.belts[row][0]
        if head.origin != origin:
            return False
        if head.is_mature(self.now):
            popped = self.belts[row].pop(0)
            # Record consumption time for CSV export
            rec = self.pallet_records.get(popped.pallet_id)
            if rec is not None and rec.get('consumido_min') is None:
                rec['consumido_min'] = self.now
            # Decrement outstanding for the origin's current lot when applicable
            if popped.lot_id == self.current_lot_id[origin] and self.current_lot_outstanding[origin] > 0:
                self.current_lot_outstanding[origin] -= 1
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

    def get_pallet_records(self) -> List[Dict[str, Any]]:
        """Return a snapshot list of pallet records for CSV export."""
        # Return as a list to avoid accidental mutation by callers
        return list(self.pallet_records.values())
