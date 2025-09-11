from math import ceil

CREATED_TIME_MIN = 24
CONSUMING_HOURS = 12
MATURATE_TIME_HOURS = 20
CREATE_MACHINE = 3

CONSUMING_TIME_MIN = CREATED_TIME_MIN / CREATE_MACHINE
LOTE_SIZE = ceil((CONSUMING_HOURS * 60) / CONSUMING_TIME_MIN)
CYCLE_BY_LOT = ceil((CONSUMING_HOURS * 60) / CONSUMING_TIME_MIN)
MATURATE_CICLE = ceil((MATURATE_TIME_HOURS * 60) / CONSUMING_TIME_MIN)

print(CONSUMING_TIME_MIN, LOTE_SIZE, CYCLE_BY_LOT, MATURATE_CICLE)

lots = []
consuming_lot = None
dynamical_lot = []
storage_lines = []
dynamic_storage_lines = []

# Generators for lot and pallet numbers
LOT_COUNTER = 0
PALLET_COUNTER = 0


def next_lot_id():
    global LOT_COUNTER
    LOT_COUNTER += 1
    return LOT_COUNTER


def next_pallet_id():
    global PALLET_COUNTER
    PALLET_COUNTER += 1
    return PALLET_COUNTER


class Pallet(object):
    source: str
    created_time: int
    id: int

    def __init__(self, source, created_time):
        self.source = source
        self.created_time = created_time
        self.id = next_pallet_id()

    @property
    def mature_time(self):
        return self.created_time + MATURATE_CICLE

    def __str__(self):
        return f"P{self.source}{self.id} [{self.created_time}/{self.mature_time}]"


class Lot(object):
    id: int
    pallets: list[Pallet]
    source: str
    creating_time: int
    creation_finished: bool = False

    def __init__(self, source, creating_time):
        self.id = next_lot_id()
        self.pallets = []
        self.source = source
        self.creating_time = creating_time

    def add_pallet(self, pallet: Pallet):
        self.pallets.append(pallet)
        if len(self.pallets) == LOTE_SIZE:
            self.creation_finished = True

    def get_next_pallet(self, cycle=None):
        # Return the next pallet only if available and mature.
        if not self.pallets:
            print(f"Cycle: {cycle} {self.source}-{self.id} EMPTY")
            return None
        pallet = self.pallets[0]
        print(f"Cycle: {cycle} {self.source}-{self.id} {pallet.mature_time} ")
        if cycle is not None and pallet.mature_time > cycle:
            # Head is not mature yet; do not pop.
            return None
        # Head exists and is mature (or cycle not provided): consume it.
        self.pallets.pop(0)
        return pallet

    def __str__(self):
        return f"{self.source}-{self.id}[{len(self.pallets)}]"


class StorageLine:
    def __init__(self, id: int, size: int, active_source: str = None):
        self.id = id
        self.size = size
        self.active_lot = None
        self.active_source = active_source
        self.pallets: list[Pallet] = []

    def __str__(self):
        return (
            f"S{self.id}[{self.active_lot if self.active_lot else ''}/"
            f"{self.active_source if self.active_source else ''}]"
            f"[{len(self.pallets)}]"
        )

    def count_mature_items(self, source: str, cycle: int) -> int:
        return sum(1 for p in self.pallets if p.source == source and p.mature_time <= cycle)

    def count_empty_spaces(self) -> int:
        return self.size - len(self.pallets)

    def can_add_pallet(self, pallet: Pallet) -> bool:
        return len(self.pallets) < self.size and (self.active_source is None or self.active_source == pallet.source)

    def add_pallet(self, pallet: Pallet) -> bool:
        if not self.can_add_pallet(pallet):
            return False
        if self.active_source is None:
            self.active_source = pallet.source
        self.pallets.append(pallet)
        return True

    def consume_pallet(self, cycle: int) -> Pallet | None:
        if not self.pallets:
            return None
        pallet = self.pallets[0]
        if pallet.mature_time > cycle:
            return None
        return self.pallets.pop(0)


def atribute_dynamic_lines():
    for line in dynamic_storage_lines:
        if line.active_lot is None:
            line.active_lot = dynamical_lot.pop(0) if dynamical_lot else None

            print("DL", line.id, line.active_lot)


def add_pallet_to_lot(pallet: Pallet):
    clot = None
    for lot in lots:
        if lot.source == pallet.source and not lot.creation_finished:
            clot = lot
            break

    if clot is None:
        clot = Lot(source=pallet.source, creating_time=pallet.created_time)
        # Remove old lot IDs for the same source
        dynamical_lot[:] = [
            lot_id
            for lot_id in dynamical_lot
            if next((lot for lot in lots if lot.id == lot_id), None).source != pallet.source
        ]

        dynamical_lot.append(clot.id)
        dynamical_lot.append(clot.id)
        atribute_dynamic_lines()
        lots.append(clot)

    clot.add_pallet(pallet)
    return clot


def create_pallet(seq) -> Pallet | None:
    source_pallet = None
    if seq % CREATE_MACHINE == 1:
        source_pallet = "A"
    elif seq % CREATE_MACHINE == 2 and seq > CYCLE_BY_LOT:
        source_pallet = "B"
    elif seq % CREATE_MACHINE == 0 and seq > CYCLE_BY_LOT * 2:
        source_pallet = "C"
    if source_pallet is None:
        return
    return Pallet(source_pallet, seq)


# def consuming(cycle):
#     global consuming_lot
#     if consuming_lot is None:
#         # pick first non-empty lot, if any
#         consuming_lot = next((lot for lot in lots if lot.pallets), None)
#         if consuming_lot is None:
#             return None
#
#     pallet = consuming_lot.get_next_pallet(cycle=cycle)
#
#     # If nothing consumable from current lot, try to advance to the next lot with pallets.
#     while pallet is None:
#         try:
#             current_lot_index = lots.index(consuming_lot)
#             # Remove the current lot if it's empty
#             if not consuming_lot.pallets:
#                 lots.pop(current_lot_index)
#         except ValueError:
#             # consuming_lot no longer in lots (shouldn't happen, but guard anyway)
#             consuming_lot = None
#             return None
#         next_lot = None
#         for i in range(current_lot_index, len(lots)):
#             if lots[i].pallets:
#                 next_lot = lots[i]
#                 break
#         if next_lot is None:
#             consuming_lot = None
#             return None
#         consuming_lot = next_lot
#         pallet = consuming_lot.get_next_pallet(cycle=cycle)
#     return pallet
#


def find_first_mature_pallet(cycle: int) -> tuple[Pallet, StorageLine] | None:
    # Check dynamic storage lines first
    for line in dynamic_storage_lines:
        pallet = line.consume_pallet(cycle)
        if pallet:
            return pallet, line

    # Then check regular storage lines
    for line in storage_lines:
        pallet = line.consume_pallet(cycle)
        if pallet:
            return pallet, line

    return None


def consuming(cycle):
    result = find_first_mature_pallet(cycle)
    if result:
        pallet, line = result
        print(f"Consumed {pallet} from {line}")
        if not line.pallets and line in dynamic_storage_lines:
            line.active_source = None
            line.active_lot = None
        return pallet
    return None


def count_mature_pallets(lot, cycle):
    count = 0
    for pallet in lot.pallets:
        if pallet.mature_time <= cycle:
            count += 1
    return count


def alocate_to_dynamic_storage(lot, pallet):
    for line in dynamic_storage_lines:
        if line.active_lot == lot.id and line.can_add_pallet(pallet):
            line.add_pallet(pallet)
            print(line, "ADD", pallet)
            return True


def alocate_to_storage(pallet):
    # Try to find a storage line already containing the same source
    for line in storage_lines:
        if line.active_source == pallet.source and line.can_add_pallet(pallet):
            line.add_pallet(pallet)
            print(line, "ADD", pallet)
            return True
    return False


if __name__ == "__main__":
    storage_size = 22
    dynamic_storage_lines = [
        StorageLine(id=1, size=storage_size),
        StorageLine(id=2, size=storage_size),
        StorageLine(id=3, size=storage_size),
    ]
    storage_lines = [
        StorageLine(id=4, size=storage_size, active_source="A"),
        StorageLine(id=5, size=storage_size, active_source="A"),
        StorageLine(id=6, size=storage_size, active_source="A"),
        StorageLine(id=7, size=storage_size, active_source="B"),
        StorageLine(id=8, size=storage_size, active_source="B"),
        StorageLine(id=9, size=storage_size, active_source="B"),
        StorageLine(id=10, size=storage_size, active_source="C"),
        StorageLine(id=11, size=storage_size, active_source="C"),
        StorageLine(id=12, size=storage_size, active_source="C"),
    ]

    for cycle in range(1, 501):
        if cycle > 328:
            consuming(cycle)

        pallet = create_pallet(cycle)

        if pallet:
            lot = add_pallet_to_lot(pallet)
            if not alocate_to_dynamic_storage(lot, pallet):
                if not alocate_to_storage(pallet):
                    atribute_dynamic_lines()
                    if not alocate_to_dynamic_storage(lot, pallet):
                        print(f"Failed to allocate {pallet} to dynamic storage")
