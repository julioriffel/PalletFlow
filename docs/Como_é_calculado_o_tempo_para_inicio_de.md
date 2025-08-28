### Como é calculado o tempo para início do consumo quando X = 24

A Fase 2 (consumo) só inicia uma janela de 12 horas para uma origem (A, B ou C) quando, no instante t, o sistema estima que haverá pallets suficientes maduros até o fim dessa janela para manter o consumo contínuo.

#### Regras usadas no código
- Maturação: cada pallet fica maduro 20 horas (1200 min) após a produção.
- Janela de consumo: 12 horas (720 min).
- Taxa de consumo: 1 pallet a cada X/3 minutos; com X=24, é 1 pallet a cada 8 minutos.
- Tamanho do lote para consumir em 12h: 12h ÷ (X/3) = 2160 / X pallets.
  - Para X = 24: lot_size = 2160 / 24 = 90 pallets.
- Critério de gatilho em t: contar pallets da origem com t_mature ≤ t + 720. Como t_mature = t_prod + 1200, isso equivale a t_prod ≤ t − (1200 − 720) = t − 480 min (ou seja, produzidos até 8 horas antes de t).

#### Tempo mínimo após ativação da origem
Para ter 90 pallets prontos até o fim da janela que começa em t, é preciso ter produzido 90 pallets até t − 8h.
- Produção: 1 pallet a cada X = 24 min.
- Tempo para produzir 90 pallets: 90 × 24 = 2160 min = 36 horas.
- Como eles precisam existir até t − 8h, adiciona-se essa folga de 8 horas ao tempo de produção para o início da janela:
  - t_início_mínimo (após ativação) = 36h + 8h = 44 horas.

#### Ativação escalonada das origens (conforme o simulador)
- A ativa em t = 0h
- B ativa em t = 12h
- C ativa em t = 24h

Portanto, os inícios mais cedo possíveis (ideais, sem bloqueios de capacidade) são:
- A: 0h + 44h = 44 horas após o início
- B: 12h + 44h = 56 horas após o início
- C: 24h + 44h = 68 horas após o início

#### Fórmula geral (resumo)
- lot_size = 2160 / X
- t_início_mín ≈ t_ativ + (lot_size × X) + (maturação − janela)
- Com maturação = 1200 min e janela = 720 min:
  - t_início_mín ≈ t_ativ + 2160 + 480 = t_ativ + 2640 min = t_ativ + 44h

#### Observações importantes
- Estes tempos são limites teóricos. Na prática, o início pode atrasar se:
  - as esteiras ficarem cheias e bloquearem a produção (capacidade 12×22),
  - a política FIFO impedir retirar um pallet maduro porque a cabeça da esteira ainda não está madura,
  - haja indisponibilidade momentânea de pallets na cabeça das três esteiras priorizadas durante a janela.