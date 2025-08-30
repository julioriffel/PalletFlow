# Simulador de Esteiras (12x22)

Aplicação de simulação com GUI (Tkinter) para organizar, maturar e consumir pallets em 12 esteiras por 22 posições.

A interface permite visualizar o estado de cada célula (vazio/A/B/C), selecionar estratégias de alocação e consumo, acompanhar o tempo simulado e exportar logs detalhados em CSV.

## Principais recursos
- Visualização em grade 12x22 com cores por tipo (A/B/C) e número do lote exibido em cada célula.
- Estratégias plugáveis de alocação e consumo, selecionáveis por combo box:
  - Alocação:
    - "Mais espaço livre"
    - "Round-robin por esteira"
    - "3 dedicadas + dinâmico (manter lote)"
  - Consumo:
    - "Priorizar 3 primeiras"
    - "Cabeça mais longa"
- Organização de esteiras: 3 dedicadas por tipo (A: 0–2, B: 4–6, C: 8–10) e 3 dinâmicas compartilhadas (linhas 3, 7 e 11).
- Cabeça da esteira (lado de consumo) à direita; inserção de novos pallets à esquerda.
- Regras de janela de consumo por tipo (12h) e maturação de pallet (20h) consideradas pelo motor de simulação.
- Exportação de CSV com: Tipo, Número do lote, Identificação do pallet, Momento de criação, Momento de consumo e Tempo entre produção e consumo (HH:MM).

## Requisitos
- Python 3.12+
- Tkinter (faz parte da biblioteca padrão Python; em algumas distros Linux é necessário instalar o pacote do sistema, ex.: `sudo apt install python3-tk`).

## Instalação
Você pode rodar diretamente com Python (não há dependências de terceiros) ou usar Poetry.

### Usando Python (venv)
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -V  # deve ser >= 3.12
```
Não há pacotes para instalar via pip.

### Usando Poetry
Poetry já está configurado em `pyproject.toml`:
```bash
poetry env use 3.12
poetry install
```

## Execução
- Via Python:
  ```bash
  python heatmap_gui.py
  ```
- Via Poetry:
  ```bash
  poetry run python heatmap_gui.py
  ```

## Uso
- X: controla a taxa de produção básica (minutos entre produções por origem; a simulação consome a cada X/3 minutos). Somente valores inteiros >= 1.
- Estratégias (combo boxes):
  - Alocação: define em qual esteira cada novo pallet será colocado.
  - Consumo: define como os pallets maduros serão escolhidos para consumo durante a janela ativa.
- Iniciar/Pausar/Reiniciar: controla o ciclo de simulação.
- Velocidade: ajusta quantos ciclos por segundo a GUI avança (1x, 2x, 4x, ...).
- Timer: mostra o tempo simulado total (dias hh:mm) com base em `engine.now`.
- Exportar CSV: salva o log dos pallets produzidos/consumidos em um arquivo CSV com as colunas:
  - Tipo, Número do lote, Identificação do pallet, Momento de criação (min), Momento de consumo (min), Tempo entre produção e consumo (HH:MM).

## Estratégias disponíveis
- Alocação:
  1) "Mais espaço livre": escolhe a esteira com mais espaço livre (empate pelo menor índice de linha).
  2) "Round-robin por esteira": alterna ciclicamente entre as esteiras dedicadas disponíveis.
  3) "3 dedicadas + dinâmico (manter lote)": três esteiras dedicadas por tipo e esteiras dinâmicas compartilhadas (3, 7, 11) usadas conforme a necessidade; prioriza manter pallets do mesmo lote na mesma esteira.
- Consumo:
  1) "Priorizar 3 primeiras": tenta consumir primeiro das esteiras dedicadas do tipo ativo e, em seguida, das dinâmicas, sempre respeitando o pallet de cabeça e a maturidade.
  2) "Cabeça mais longa": escolhe a esteira (dedicada ou dinâmica) com a fila mais longa cuja cabeça seja um pallet maduro do tipo ativo.

## Organização das esteiras
- Dedicadas por tipo:
  - A: linhas 0, 1, 2
  - B: linhas 4, 5, 6
  - C: linhas 8, 9, 10
- Dinâmicas compartilhadas: linhas 3, 7, 11 (podem receber excedentes de qualquer tipo conforme a estratégia).
- Visualização: a célula mais à direita de cada linha é o próximo pallet a ser consumido (cabeça da fila).

## Janelas de consumo e maturação
- Maturação de cada pallet: 20 horas (configuração padrão no motor).
- Janela de consumo por tipo: 12 horas rotativas entre A, B e C. Uma janela começa quando há pallets suficientes maduros/para maturar ao longo da janela (o motor avalia automaticamente os critérios de início).

## Estrutura do projeto
```
.
├─ heatmap_gui.py       # GUI Tkinter (aplicação, controles, exportação CSV, log)
├─ simulation.py        # Lógica de simulação, estratégias plugáveis e eventos
├─ docs/
│  └─ Como_é_calculado_o_tempo_para_inicio_de.md
├─ pyproject.toml       # Configuração (Poetry), Python >=3.12
└─ README.md            # Este arquivo
```

## Notas de desenvolvimento
- O código separa a lógica de negócios (simulation.py) da GUI (heatmap_gui.py).
- Para verificar imports rapidamente:
  ```bash
  python -c "import simulation, heatmap_gui; print('OK')"
  ```
- Exportação CSV: os registros são mantidos por pallet, incluindo hora de criação (`criado_min`) e de consumo (`consumido_min`). O tempo entre produção e consumo é calculado e exportado em formato HH:MM.

## Licença
Defina uma licença para este projeto (por exemplo, MIT, Apache-2.0). Atualize esta seção conforme necessário.
