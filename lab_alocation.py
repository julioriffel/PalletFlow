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
dynamical_lot_ids = []
fix_storage_lines = []
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

    def simple(self, cycle):
        return f"P{self.source}{'*' if cycle >= self.mature_time else ''}{self.id}"


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

    def __str__(self):
        return f"{self.source}-{self.id}[{len(self.pallets)}]"

    def count_mature_pallets(self, cycle):
        count = 0
        for pallet in self.pallets:
            if pallet.mature_time <= cycle:
                count += 1
        return count


class StorageLine:
    def __init__(self, id: int, size: int, active_source: str = None):
        self.id = id
        self.size = size
        self.active_lot = None
        self.active_source = active_source
        self.pallets: list[Pallet] = []

    def __str__(self):
        return f"S{self.id}[{self.active_lot if self.active_lot else self.active_source}][{len(self.pallets)}]"

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
        print(self, "ADD", pallet)
        return True

    def consume_pallet(self, cycle: int) -> Pallet | None:
        if not self.pallets:
            return None
        pallet = self.pallets[0]
        if pallet.mature_time > cycle:
            return None
        pallet = self.pallets.pop(0)
        print(self, "CONSUME", pallet)
        return pallet

    def print_resume(self):
        output = str(self)
        for p in self.pallets:
            output += f"| {p.simple(cycle)}"
        print(output)


def assign_dynamic_lines(remove_lot=None):
    if remove_lot:
        for line in dynamic_storage_lines:
            if line.active_lot <= remove_lot:
                line.active_lot = None

    for lot in lots:
        if lot.creation_finished:
            for line in dynamic_storage_lines:
                if line.active_lot <= lot.id:
                    line.active_lot = None

    for line in dynamic_storage_lines:
        if line.active_lot is None:
            line.active_lot = dynamical_lot_ids.pop(0) if dynamical_lot_ids else None

            if line.active_lot:
                line.active_source = next((lot.source for lot in lots if lot.id == line.active_lot), None)
                print("Dynamic Line Assigned line:", line.id, line.active_lot)


def add_pallet_to_lot(pallet: Pallet):
    clot = None
    for lot in lots:
        if lot.source == pallet.source and not lot.creation_finished:
            clot = lot
            break

    if clot is None:
        clot = Lot(source=pallet.source, creating_time=pallet.created_time)
        print("New lot created:", clot)
        # Remove old lot IDs for the same source
        dynamical_lot_ids[:] = [
            lot_id
            for lot_id in dynamical_lot_ids
            if next((lot for lot in lots if lot.id == lot_id), None).source != pallet.source
        ]

        dynamical_lot_ids.append(clot.id)
        dynamical_lot_ids.append(clot.id)
        assign_dynamic_lines()
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


def consuming_by_storage(consuming_lot, cycle):
    # Check all storage lines for mature pallets from consuming lot
    for line in fix_storage_lines:
        if line.active_source == consuming_lot.source:
            pallet = line.consume_pallet(cycle)
            if pallet is not None:
                return pallet
    return None


def consuming_by_dynamic(consuming_lot, cycle):
    mature_lines = []

    # Check all dynamic storage lines for mature pallets from consuming lot
    for line in dynamic_storage_lines:
        if line.pallets and line.pallets[0].source == consuming_lot.source and line.pallets[0].mature_time <= cycle:
            mature_lines.append(line)

    if not mature_lines:
        return None

    # If multiple lines have mature pallets, choose the one with least empty spaces
    if len(mature_lines) > 1:
        mature_lines.sort(key=lambda x: x.active_lot)
    if len(mature_lines) > 1:
        mature_lines.sort(key=lambda x: x.count_empty_spaces())

    # Consume from the selected line
    return mature_lines[0].consume_pallet(cycle)


def update_consuming_lot():
    global consuming_lot
    consuming_lot = lots.pop(0) if lots else None
    if consuming_lot is not None:
        assign_dynamic_lines(remove_lot=consuming_lot.id)
    return consuming_lot


def consuming(cycle):
    global consuming_lot

    if consuming_lot is None:
        # pick first non-empty lot, if any
        consuming_lot = update_consuming_lot()
        if consuming_lot is None:
            return None
    pallet = None
    if storage_source_is_full(consuming_lot.source):
        pallet = consuming_by_storage(consuming_lot, cycle)
    if pallet is None:
        pallet = consuming_by_dynamic(consuming_lot, cycle)
    if pallet is None:
        pallet = consuming_by_storage(consuming_lot, cycle)
    if pallet is None:
        consuming_lot = update_consuming_lot()
        print_full_resume(cycle)
        pallet = consuming(cycle)
    return pallet


def alocate_to_dynamic_storage(lot, pallet):
    for line in dynamic_storage_lines:
        if line.active_lot == lot.id and line.add_pallet(pallet):
            return True


def alocate_to_storage(pallet):
    # Try to find a storage line already containing the same source
    for line in fix_storage_lines:
        if line.active_source == pallet.source and line.can_add_pallet(pallet):
            line.add_pallet(pallet)
            return True
    return False


def storage_source_is_full(source):
    for line in fix_storage_lines:
        if line.active_source == source and line.count_empty_spaces() > 0:
            return False
    return True


def print_full_resume(cycle=None):
    print(f"Resume cycle: {cycle}")
    for line in dynamic_storage_lines:
        line.print_resume()
    for line in fix_storage_lines:
        line.print_resume()


if __name__ == "__main__":
    storage_size = 22
    dynamic_storage_lines = [
        StorageLine(id=1, size=storage_size),
        StorageLine(id=2, size=storage_size),
        StorageLine(id=3, size=storage_size),
    ]
    fix_storage_lines = [
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

    for cycle in range(1, 399):
        if cycle >= 328:
            consuming(cycle)

        pallet = create_pallet(cycle)

        if pallet:
            lot = add_pallet_to_lot(pallet)
            if not alocate_to_dynamic_storage(lot, pallet):
                if not alocate_to_storage(pallet):
                    assign_dynamic_lines()
                    if not alocate_to_dynamic_storage(lot, pallet):
                        print_full_resume(cycle)
                        print(f"Failed to allocate {lot} {pallet} to dynamic storage")
                        print("--")
