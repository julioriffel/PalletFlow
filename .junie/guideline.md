# Simulação da Linha de Produção — Explicação do Algoritmo de Cálculo (PT-BR)

Este projeto simula uma linha de produção com duas fases e um pulmão de maturação em esteiras. 

## Premissas e parâmetros
- Fase 1 (produção): 3 máquinas (A, B, C), cada uma produz 1 pallet a cada X minutos.
- Maturação: cada pallet precisa esperar 20 horas antes de poder ser consumido na Fase 2.
- Pulmão/esteiras: 12 esteiras, 22 posições cada (capacidade total 12 × 22 = 264). Cada esteira é FIFO e unidirecional.
- Fase 2 (consumo): 1 pallet a cada X/3 minutos.
  - Taxa Fase 2: 3x maior que a fase 1
- Lote de consumo: a Fase 2 consome durante janelas de 12 horas pallets de UMA ÚNICA origem (A, B ou C), sem misturar.
- X se refere ao tempo necessário para produção de um pallet (em média 24 minutos), podendo ser alterado. X/3 é o tempo para consumo de um pallet (8 minutos)

Observação: As taxas de produção e consumo são iguais. Isso permite, em princípio, operação estável sem acúmulo indefinido, desde que o pulmão não bloqueie localmente.

## Gatilho de pallets maduros?
A Fase 2 só deve iniciar quando houver pallets suficientes para iniciar o processamento contínuo por 12 horas sem parar, considerando os pallets já maduros e os que vão amadurecer durante a janela de processamento.
 Assim, para não parar a Fase 2, precisamos começar a janela com estoque maduro suficiente para atravessar a janela, sem manter muitos pallets em estoque devido à limitação de espaço.

## Início de Produção escalonado:
A ativação das máquinas da Fase 1 deve ser escalonada em 12 horas, de maneira a garantir que não exista estoque desnecessário.

## Estrutura do algoritmo (visão de alto nível)
1. Produtores (A, B, C):
   - A cada X min, criam um pallet com `t_prod = tempo_atual` e tentam depositar em uma esteira atribuída à sua origem.
   - Se não houver espaço, ficam bloqueados e tentam novamente periodicamente (isso acumula `block_time`).
2. Maturação nas esteiras:
   - Cada esteira é FIFO. Um pallet é “pronto” quando `now − t_prod ≥ 20 h`.
   - Para respeitar FIFO, apenas se o pallet NA CABEÇA estiver pronto podemos retirá-lo; se não estiver, aguardamos (mesmo que algum atrás esteja maduro).
3. Scheduler de lotes (Fase 2):
   - Faz um rodízio A → B → C em janelas de 12 h (ajustar o tempo para consumir o lote totalmente).
   - Antes de iniciar o lote de uma origem, verificar se há quantidade suficiente de pallets maduros.
   - Durante a janela, a cada X/3 min, tentar retirar 1 pallet pronto daquela origem; priorizar 3 esteiras — de preferência aquelas cujos itens estarão maduros ao final do próximo lote — e consumir 1 pallet de cada esteira.
4. Alocação de esteiras:
   - Propor diversos algoritmos de alocação de esteira e distribuição de pallets para garantir que as máquinas nunca parem.


## Dúvidas/Questionamentos em Aberto

- Parâmetros e taxas de processo:
  - Qual o valor padrão de X? 24 minutos é apenas exemplo ou default? Há variação (determinística vs. estocástica)? Qual distribuição e desvio padrão, se aplicável?
  - O tempo de maturação (20 horas) é fixo para todos os pallets ou pode variar por pallet/lote? Existe tolerância (ex.: 19h30) ou é estritamente ≥ 20h?
  - Existe tempo de setup/troca na Fase 2 ao alternar a origem (A→B→C)? Se sim, qual a duração e se a janela de 12h inclui esse setup?

- Capacidade do pulmão e política de esteiras:
  - As esteiras são dedicadas por origem (A, B, C) ou são compartilhadas? Se dedicadas, quantas por origem? Se compartilhadas, qual a regra de atribuição?
  - Política de depósito quando há múltiplas esteiras com espaço: round-robin, menor ocupação, maior folga até bloquear, ou outra?
  - FIFO é estrito: se o pallet na cabeça não estiver maduro, nunca se retira um pallet posterior, correto? Existe alguma exceção (by-pass) permitida?

- Lotes e scheduler (Fase 2):
  - Critério quantitativo para “estoque maduro suficiente” para iniciar a janela de 12h: qual o número mínimo de pallets maduros no instante inicial? Consideramos também os que amadurecerão durante a janela com alguma margem de segurança? Qual?
  - O rodízio A→B→C é sempre fixo ou pode ser adaptativo com base na disponibilidade de pallets maduros/capacidade do pulmão? Pode-se pular uma origem se não cumprir o gatilho?
  - Seleção das 3 esteiras priorizadas: como escolher? Sempre 3 ou quantidade ajustável conforme a disponibilidade?

- Consumo e cadência na Fase 2:
  - O consumo “1 pallet a cada X/3 min” é rígido (ticks fixos) ou existe uma fila de serviço com possibilidade de compensar atrasos (catch-up)?
  - Se no instante de consumo não houver pallet pronto da origem, a Fase 2 espera até o próximo tick, busca em outras esteiras da mesma origem, ou considera trocar de origem/lote?
  - É permitido consumir de esteiras adicionais da mesma origem além das 3 priorizadas caso uma delas bloqueie por maturação?

- Início de Produção escalonado (Fase 1):
  - “Escalonada em 12 horas” significa defasagem de 12h entre A, B e C (ex.: A em t0, B em t0+12h, C em t0+24h) ou outra lógica? Qual o objetivo primário: reduzir WIP, evitar pico no pulmão, ou sincronizar com a Fase 2?
  - Em caso de falta de espaço no pulmão, qual o intervalo de retentativa dos produtores? Existe backoff exponencial ou intervalo fixo?

- Bloqueios, descarte e validade:
  - Se o pulmão estiver cheio, a produção pausa (máquinas param) ou pallets são descartados/colocados em espera fora do sistema?
  - Existe tempo máximo de permanência no pulmão (pallet expira)? O que fazer se exceder (descartar, reprocessar, marcar como inválido)?

- Métricas e resultados esperados:
  - Quais KPIs monitorar: throughput por origem, utilização de máquinas, tempo médio de espera/maturação, WIP médio, taxa de bloqueio por máquina e por esteira, perdas por falta de maturação/por espaço.
  - Há metas/limiares de desempenho aceitáveis para validar a simulação (ex.: utilização > 85%, bloqueio < 5%)?

- Configuração e reprodutibilidade:
  - Quais parâmetros devem ser configuráveis (X, janelas de lote, número de esteiras, capacidade por esteira, tempo de maturação, política de alocação, semente aleatória)?
  - Unidade e passo de tempo da simulação: minutos como unidade; simulação discreta por evento ou em passos fixos? Precisão exigida (ex.: 1 min)?

- Restrições e regras de negócio adicionais:
  - Misturar origens no pulmão é permitido, porém o consumo da Fase 2 não mistura na mesma janela — confirmar. Há restrições físicas de layout (ex.: esteiras específicas só acessíveis pela Fase 2 em determinados horários)?
  - Pallets ocupam sempre 1 posição? Há variação de tamanho que impacte a capacidade efetiva por esteira?

- Validação e cenários de teste:
  - Existe um cenário-base esperado para validação (ex.: X=24 min, 7 dias de simulação) com valores de referência de WIP, throughput e bloqueios?
  - Devemos considerar cenários de estresse (pulmão no limite, variação de X, falhas temporárias) para validar robustez?
