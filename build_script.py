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


class Pallet(object):
    type: str
    created_time: int

    def __init__(self, type, created_time):
        self.type = type
        self.created_time = created_time

    @property
    def mature_time(self):
        return self.created_time + MATURATE_CICLE

    def __str__(self):
        return f"Pallet {self.type} created at {self.created_time} will mature at {self.mature_time}"


class Lot(object):
    id: int
    pallets: list[Pallet]
    type: str
    creating_time: int
    creation_finished: bool = False

    def __init__(self, type, creating_time):
        self.id = len(lots) + 1
        self.pallets = []
        self.type = type
        self.creating_time = creating_time

    def add_pallet(self, pallet: Pallet):
        self.pallets.append(pallet)
        if len(self.pallets) == LOTE_SIZE:
            self.creation_finished = True

    def get_next_pallet(self, cycle=None):
        pallet = self.pallets.pop(0)
        print(f"Cycle: {cycle} {self.type}-{self.id} {pallet.mature_time} ")
        if pallet.mature_time > cycle:
            raise Exception("Pallet NOT Mature")

        return pallet

    def __str__(self):
        return f"Lot {self.type}-{self.id} created at {self.creating_time} has {len(self.pallets)} pallets"


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
        consuming_lot = lots[0]

    pallet = consuming_lot.get_next_pallet(cycle=cycle)

    if pallet is None:
        current_lot_index = lots.index(consuming_lot)
        if current_lot_index + 1 < len(lots):
            consuming_lot = lots[current_lot_index + 1]
            pallet = consuming_lot.get_next_pallet(cycle=cycle)
        else:
            consuming_lot = None
    return pallet

def count_mature_pallets(lot):
    count = 0
    for pallet in lot.pallets:
        if pallet.mature_time <= cycle:
            count += 1
    return count

for cycle in range(1, 5001):
    pallet = create_pallet(cycle)

    if pallet:
        add_pallet_to_lot(pallet)

    print(count_mature_pallets(lots[0]), cycle)

    if cycle > 328:
        consuming(cycle)
