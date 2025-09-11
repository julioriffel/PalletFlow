from math import ceil

CREATED_TIME_MIN = 24
CONSUMING_HOURS = 12
MATURATE_TIME_HOURS = 20
CREATE_MACHINE = 3

CONSUMING_TIME_MIN = CREATED_TIME_MIN / CREATE_MACHINE
LOTE_SIZE = ceil((CONSUMING_HOURS * 60) / CONSUMING_TIME_MIN)
CYCLE_BY_LOT = ceil((CONSUMING_HOURS * 60) / CREATED_TIME_MIN)
MATURATE_CICLE = ceil((MATURATE_TIME_HOURS * 60) / CONSUMING_TIME_MIN)

print(CONSUMING_TIME_MIN, LOTE_SIZE, CYCLE_BY_LOT, MATURATE_CICLE)

lots = []
consuming_lot = None

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
    type: str
    created_time: int
    id: int

    def __init__(self, type, created_time):
        self.type = type
        self.created_time = created_time
        self.id = next_pallet_id()

    @property
    def mature_time(self):
        return self.created_time + MATURATE_CICLE

    def __str__(self):
        return f"P {self.type}{self.id} {self.created_time}/{self.mature_time}"


class Lot(object):
    id: int
    pallets: list[Pallet]
    type: str
    creating_time: int
    creation_finished: bool = False

    def __init__(self, type, creating_time):
        self.id = next_lot_id()
        self.pallets = []
        self.type = type
        self.creating_time = creating_time

    def add_pallet(self, pallet: Pallet):
        self.pallets.append(pallet)
        if len(self.pallets) == LOTE_SIZE:
            self.creation_finished = True

    def get_next_pallet(self, cycle=None):
        # Return the next pallet only if available and mature.
        if not self.pallets:
            print(f"Cycle: {cycle} {self.type}-{self.id} EMPTY")
            return None
        pallet = self.pallets[0]
        print(f"Cycle: {cycle} {self.type}-{self.id} {pallet.mature_time} ")
        if cycle is not None and pallet.mature_time > cycle:
            # Head is not mature yet; do not pop.
            return None
        # Head exists and is mature (or cycle not provided): consume it.
        self.pallets.pop(0)
        return pallet

    def __str__(self):
        return f"L{self.type}-{self.id}[{len(self.pallets)}]"


def add_pallet_to_lot(pallet: Pallet):
    clot = None
    for lot in lots:
        if lot.type == pallet.type and not lot.creation_finished:
            clot = lot
            break

    if clot is None:
        clot = Lot(type=pallet.type, creating_time=pallet.created_time)
        lots.append(clot)

    clot.add_pallet(pallet)
    print(clot)


def create_pallet(seq) -> Pallet | None:
    type_pallet = None
    if seq % CREATE_MACHINE == 1:
        type_pallet = "A"
    elif seq % CREATE_MACHINE == 2 and seq > CYCLE_BY_LOT:
        type_pallet = "B"
    elif seq % CREATE_MACHINE == 0 and seq > CYCLE_BY_LOT * 2:
        type_pallet = "C"
    if type_pallet is None:
        return
    return Pallet(type_pallet, seq)


def consuming(cycle):
    global consuming_lot
    if consuming_lot is None:
        # pick first non-empty lot, if any
        consuming_lot = next((lot for lot in lots if lot.pallets), None)
        if consuming_lot is None:
            return None

    pallet = consuming_lot.get_next_pallet(cycle=cycle)

    # If nothing consumable from current lot, try to advance to the next lot with pallets.
    while pallet is None:
        try:
            current_lot_index = lots.index(consuming_lot)
            # Remove the current lot if it's empty
            if not consuming_lot.pallets:
                lots.pop(current_lot_index)
        except ValueError:
            # consuming_lot no longer in lots (shouldn't happen, but guard anyway)
            consuming_lot = None
            return None
        next_lot = None
        for i in range(current_lot_index, len(lots)):
            if lots[i].pallets:
                next_lot = lots[i]
                break
        if next_lot is None:
            consuming_lot = None
            return None
        consuming_lot = next_lot
        pallet = consuming_lot.get_next_pallet(cycle=cycle)
    return pallet


def count_mature_pallets(lot, cycle):
    count = 0
    for pallet in lot.pallets:
        if pallet.mature_time <= cycle:
            count += 1
    return count


for cycle in range(1, 501):
    pallet = create_pallet(cycle)

    if pallet:
        add_pallet_to_lot(pallet)

    if lots:
        print(cycle, lots[0], count_mature_pallets(lots[0], cycle))
    else:
        print(0, cycle)
    if cycle > 328:
        consuming(cycle)
