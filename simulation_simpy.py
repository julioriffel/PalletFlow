import simpy
from collections import deque, defaultdict

# Optional plotting support
try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:
    plt = None

MIN = 1
H = 60
MATURACAO = 20 * H

PROD_INTERVAL = 24 * MIN  # 1 pallet/24min por máquina F1
CONS_INTERVAL = PROD_INTERVAL / 3  # 1 pallet F2
BATCH_HOURS = 12 * H  # 12h por lote (origem única)
BATCH_PALLETS = BATCH_HOURS // CONS_INTERVAL  # 90

N_LANES = 12
LANE_CAP = 22


class Pallet:
    def __init__(self, id_, origem, t_prod):
        self.id = id_
        self.origem = origem  # 'A', 'B', ou 'C'
        self.t_prod = t_prod

    def pronto(self, now):
        return (now - self.t_prod) >= MATURACAO


class Esteira:
    def __init__(self, name, cap=LANE_CAP):
        self.name = name
        self.cap = cap
        self.q = deque()  # FIFO
        self.origem = None  # origem atualmente atribuída para recebimento

    def space(self):
        return self.cap - len(self.q)

    def push(self, pallet):
        if len(self.q) >= self.cap:
            return False
        self.q.append(pallet)
        return True

    def peek_ready(self, now):
        if self.q and self.q[0].pronto(now):
            return self.q[0]
        return None

    def pop_ready(self, now):
        p = self.peek_ready(now)
        if p:
            self.q.popleft()
            return p
        return None


class Sistema:
    def __init__(self, env):
        self.env = env
        self.esteiras = [Esteira(f"E{i}") for i in range(N_LANES)]
        self.id_counter = 0
        # KPIs
        self.block_time = defaultdict(float)  # por origem
        self.consumidos = 0
        self.consumidos_por_origem = defaultdict(int)
        self.idle_time_f2 = 0.0
        self.uso_esteiras_hist = []
        # Eventos de criação/consumo (tuplas: (tempo_min, tipo, origem))
        self.events = []
        # Estado do lote atual (para UI): origem em consumo e quantidade já consumida
        self.current_batch_origin = None  # 'A' | 'B' | 'C' | None
        self.current_batch_count = 0  # 0..BATCH_PALLETS durante a janela

    def total_ocupacao(self):
        return sum(len(e.q) for e in self.esteiras)

    def uso_snapshot(self):
        load = {e.name: (e.origem, len(e.q)) for e in self.esteiras}
        self.uso_esteiras_hist.append((self.env.now, load))

    def log_event(self, tipo: str, origem: str):
        # tipo: 'created' ou 'consumed'
        # origem: 'A', 'B' ou 'C'
        self.events.append((self.env.now, tipo, origem))

    # Política de alocação dinâmica de esteiras
    def assign_lanes(self, quotas):
        # quotas: dict origem->n_est, e.g., {'A':5,'B':4,'C':3}
        # objetivo: ajustar e.origem conforme quotas e ocupação atual, evitando mover pallets
        # Regras: só mude origem em esteiras vazias; não reatribua esteiras com fila.
        # Passo 1: conte atuais
        current = defaultdict(list)
        empty = []
        for e in self.esteiras:
            if len(e.q) == 0:
                empty.append(e)
            if e.origem:
                current[e.origem].append(e)
        # Passo 2: garanta quotas usando vazias
        for origem, need in quotas.items():
            have = len([e for e in self.esteiras if e.origem == origem])
            while have < need and empty:
                e = empty.pop()
                e.origem = origem
                have += 1
        # Esteiras remanescentes vazias ficam sem origem até necessidade

    def push_pallet(self, pallet):
        # tente esteiras da mesma origem com espaço
        # se nenhuma tiver espaço, tente atribuir uma esteira vazia
        # se ainda não, bloqueia
        # Preferir esteira com mais espaço para consolidar
        candidates = [e for e in self.esteiras if e.origem == pallet.origem and e.space() > 0]
        if not candidates:
            empties = [e for e in self.esteiras if len(e.q) == 0 and e.origem in (None, pallet.origem)]
            if empties:
                e = empties[0]
                e.origem = pallet.origem
                return e.push(pallet)
            else:
                # Sem espaço
                return False
        # escolhe a com maior espaço disponível
        e = max(candidates, key=lambda x: x.space())
        return e.push(pallet)

    def matured_inventory(self, origem):
        now = self.env.now
        count = 0
        for e in self.esteiras:
            if e.origem == origem:
                # contar apenas os prontos na cabeça e atrás deles que já estejam prontos
                for p in e.q:
                    if p.pronto(now):
                        count += 1
                    else:
                        break  # FIFO: se este não está pronto, os de trás podem até estar prontos, mas não liberáveis nesta esteira
        return count

    def pop_one_for(self, origem):
        now = self.env.now
        # tente retirar de qualquer esteira dessa origem com cabeça pronta
        # escolha a esteira com maior fila (para consolidar liberações)
        candidates = []
        for e in self.esteiras:
            if e.origem == origem and e.peek_ready(now):
                candidates.append(e)
        if not candidates:
            return None
        e = max(candidates, key=lambda x: len(x.q))
        return e.pop_ready(now)


def produtor(env, sistema: Sistema, origem: str):
    while True:
        # produzir
        yield env.timeout(PROD_INTERVAL)
        p = Pallet(sistema.id_counter, origem, env.now)
        sistema.id_counter += 1
        # log de criação do container
        sistema.log_event('created', origem)
        # tentar armazenar, ou bloquear até liberar espaço
        start_wait = env.now
        while not sistema.push_pallet(p):
            yield env.timeout(1)  # espera 1 min antes de tentar de novo
        wait = env.now - start_wait
        if wait > 0:
            sistema.block_time[origem] += wait


def scheduler_lotes(env, sistema: Sistema):
    # política simples: rodada A->B->C, mas só inicia lote se maturados >= 60.
    ordem = ['A', 'B', 'C']
    idx = 0
    while True:
        alvo = ordem[idx]
        # ajustar quotas (mais esteiras para "alvo")
        # heurística: 5/4/3 distribuídas com base no alvo
        quotas = {alvo: 5, ordem[(idx + 1) % 3]: 4, ordem[(idx + 2) % 3]: 3}
        sistema.assign_lanes(quotas)
        # esperar até haver pelo menos 60 maturados
        while sistema.matured_inventory(alvo) < 60:
            yield env.timeout(5)  # reavalia a cada 5 min
        # sinalizar início do lote
        sistema.current_batch_origin = alvo
        sistema.current_batch_count = 0
        fim_lote = env.now + BATCH_HOURS
        while env.now < fim_lote:
            # consumo a cada 8 min, se houver pallet pronto
            if sistema.matured_inventory(alvo) == 0:
                # aguarda próximo desbloqueio (maturação/chegada à cabeça)
                start_idle = env.now
                # dormir um pouco até que pelo menos um esteja pronto
                # (vá de 1 em 1 min para reavaliar)
                while sistema.matured_inventory(alvo) == 0 and env.now < fim_lote:
                    yield env.timeout(1)
                sistema.idle_time_f2 += env.now - start_idle
            # retirar um pallet se disponível
            pallet = sistema.pop_one_for(alvo)
            if pallet is not None:
                sistema.consumidos += 1
                sistema.consumidos_por_origem[alvo] += 1
                sistema.log_event('consumed', alvo)
                # atualizar contagem do lote atual
                if sistema.current_batch_origin == alvo:
                    sistema.current_batch_count += 1
            # aguardar próximo ciclo de consumo
            yield env.timeout(CONS_INTERVAL)
        # fim do lote
        sistema.current_batch_origin = None
        idx = (idx + 1) % 3


def coleta_kpis(env, sistema: Sistema, intervalo=60):
    while True:
        sistema.uso_snapshot()
        yield env.timeout(intervalo)


def export_events_csv(events, filename='container_events.csv'):
    # Exporta eventos para CSV com colunas: time_min,tipo,origem
    try:
        events_sorted = sorted(events, key=lambda x: x[0])
        with open(filename, 'w') as f:
            f.write('time_min,tipo,origem\n')
            for t, tipo, origem in events_sorted:
                f.write(f'{int(t)},{tipo},{origem}\n')
        print(f'Eventos exportados para: {filename}')
    except Exception as e:
        print(f'Falha ao salvar CSV de eventos: {e}')


def display_container_flow(events, filename='container_flow.png'):
    # Gera gráfico (PNG) da criação vs consumo ao longo do tempo, se matplotlib estiver disponível
    if plt is None:
        print('matplotlib não encontrado; pulando geração de gráfico. O CSV foi gerado.')
        return None
    events_sorted = sorted(events, key=lambda x: x[0])
    if not events_sorted:
        print('Sem eventos para plotar.')
        return None
    # Construir séries cumulativas
    times = []
    created_cum = []
    consumed_cum = []
    c_created = 0
    c_consumed = 0
    last_t = None
    for t, tipo, _ in events_sorted:
        if last_t is not None and t != last_t:
            # manter o valor até o próximo instante (para step)
            times.append(last_t)
            created_cum.append(c_created)
            consumed_cum.append(c_consumed)
        last_t = t
        if tipo == 'created':
            c_created += 1
        elif tipo == 'consumed':
            c_consumed += 1
        times.append(t)
        created_cum.append(c_created)
        consumed_cum.append(c_consumed)
    # Converter minutos para horas
    times_h = [t / 60.0 for t in times]
    import matplotlib.pyplot as _plt  # garantir namespace local
    _plt.figure(figsize=(10, 6))
    _plt.step(times_h, created_cum, where='post', label='Criados (acum.)')
    _plt.step(times_h, consumed_cum, where='post', label='Consumidos (acum.)')
    _plt.xlabel('Tempo (horas)')
    _plt.ylabel('Containers (acumulado)')
    _plt.title('Criação vs Consumo de Containers')
    _plt.legend()
    _plt.grid(True, alpha=0.3)
    try:
        _plt.tight_layout()
        _plt.savefig(filename)
        _plt.close()
        print(f'Gráfico salvo em: {filename}')
        return filename
    except Exception as e:
        print(f'Falha ao salvar gráfico: {e}')
        _plt.close()
        return None


def simular(horas=7 * 24):
    env = simpy.Environment()
    sistema = Sistema(env)
    # produtores
    env.process(produtor(env, sistema, 'A'))
    env.process(produtor(env, sistema, 'B'))
    env.process(produtor(env, sistema, 'C'))
    # scheduler de lotes e coleta de KPIs
    env.process(scheduler_lotes(env, sistema))
    env.process(coleta_kpis(env, sistema, intervalo=30))

    # Inicializar visualização ao vivo das esteiras (import adiado para evitar ciclo)
    try:
        from real import start_live_esteira_viewer  # type: ignore
        start_live_esteira_viewer(env, sistema, refresh_min=8)
    except Exception as _e:
        # Se houver erro (ex.: ambiente sem GUI), apenas informar e seguir
        print(f"Viewer ao vivo indisponível: {_e}")

    env.run(until=horas * H)

    # Relatório
    print('--- Resultados ---')
    print(f"Tempo simulado: {horas} h")
    print(f"Total consumido F2: {sistema.consumidos} pallets")
    print("Consumidos por origem:", dict(sistema.consumidos_por_origem))
    print(f"Ociosidade F2 (min): {sistema.idle_time_f2:.1f}")
    print("Tempo bloqueio F1 por origem (min):", {k: round(v, 1) for k, v in sistema.block_time.items()})
    ocup_total = [sum(v2 for _, v2 in snap.values()) for _, snap in sistema.uso_esteiras_hist]
    if ocup_total:
        print(f"Ocupação média total nas esteiras: {sum(ocup_total) / len(ocup_total):.1f} pallets")

    # Exportar eventos e gerar exibição
    export_events_csv(sistema.events, 'container_events.csv')
    img_path = display_container_flow(sistema.events, 'container_flow.png')
    if img_path:
        print(f"Exibição gerada: {img_path}")

    return sistema


if __name__ == '__main__':
    simular(horas=60 * 24)  # 14 dias
