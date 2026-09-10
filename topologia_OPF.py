"""
Rede de Transporte de Portugal Continental (RNT) - PyPSA
==========================================================
DESPACHO ECONOMICO (OPF) COM ATLITE + COMPENSACAO ITERATIVA DE PERDAS
+ DIAGNOSTICO/FALLBACK GUROBI

A construcao da rede (barramentos, linhas, transformadores, cargas,
geracao, importacao) esta agora no modulo partilhado rede_base.py -
ver esse ficheiro para os detalhes dessa parte. Este script trata so
do que e especifico dele: desenho do mapa, atlite/ERA5, custos
marginais, despacho por OPF e compensacao iterativa de perdas.
"""

import os
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from rede_base import construir_rede, resolver_pf_respeitando_capacidade

# <<< Define aqui a data/hora exata do cenario a simular - funciona para
# QUALQUER instante de 2024 presente no registo da REN >>>
TIMESTAMP_CENARIO_ALVO =   "2024-01-08 19:45:00"

# Cenarios de referencia (nao usados pelo codigo - alterar a linha acima
# para simular outra data):
#   "2024-01-08 19:45:00"  # Maximo Inverno
#   "2024-05-12 06:30:00"  # Minimo Absoluto
#   "2024-04-25 15:30:00"  # Maxima Injecao Renovavel
#   "2024-07-24 19:45:00"  # Maximo Verao

# ===========================================================================
# 1. OPCOES DE SIMULACAO - configurar aqui antes de correr o script
# ===========================================================================
# CORRER_ATLITE: calcula o fator de capacidade renovavel (Seccao 4) via
# atlite/ERA5. Ao contrario do topologia.py, aqui e um LIMITE REAL da
# otimizacao (p_max_pu), nao so um limite de seguranca.
CORRER_ATLITE = True

# CORRER_OPF: ativa o despacho economico (OPF) com compensacao iterativa
# de perdas (Seccao 5). Ver nota metodologica completa junto a essa
# seccao, mais abaixo no ficheiro.
CORRER_OPF = True
MAX_ITER_PERDAS = 10
TOL_PERDAS_MW = 1.0  # criterio de convergencia das perdas, em MW

# DISTRIBUIR_SLACK: reparte o desequilibrio entre despacho otimizado e
# carga+perdas por todos os geradores sincronos (hidrica/fossil/biomassa),
# proporcionalmente ao despacho - em vez de o concentrar inteiramente no
# unico gerador Slack. Eolica e solar excluidas (peso 0), por nao
# participarem da regulacao primaria de frequencia real. Ver nota
# completa na Seccao 4 do topologia.py, onde foi validado primeiro.
DISTRIBUIR_SLACK = True
CARRIERS_EXCLUIDOS_DO_SLACK = ["wind", "solar", "import"]

# CALIBRAR_CUSTO_FOSSIL: ativa a calibracao exploratoria de custos
# marginais (Seccao 5.1), que procura o custo que aproxima o despacho do
# OPF do despacho real. NAO substitui os custos da Seccao 3 nem se
# destina a isso - ver nota metodologica completa junto a essa seccao.
CALIBRAR_CUSTO_FOSSIL = False
LIMIAR_APROXIMACAO_PCT = 10.0  # ver Fase 1 - abaixo disto, nao avanca para a Fase 2
CUSTO_MIN_BISSECAO = 0.0
CUSTO_MAX_BISSECAO = 300.0
MAX_ITER_BISSECAO = 25
TOL_BISSECAO_MW = 1.0

ctx = construir_rede(TIMESTAMP_CENARIO_ALVO)
n = ctx.n
CAMINHO = ctx.CAMINHO

# Pasta de cache, criada automaticamente na primeira execucao. Guarda os
# dados meteorologicos descarregados pelo atlite e as redes exportadas em
# formato NetCDF, ficheiros grandes que nao devem ser versionados.
CACHE = os.path.join(CAMINHO, "cache") + os.sep
os.makedirs(CACHE, exist_ok=True)

# Pasta dos resultados gerados por este script (mapas, graficos, tabelas),
# criada automaticamente na primeira execucao.
RESULTADOS = os.path.join(CAMINHO, "resultados") + os.sep
os.makedirs(RESULTADOS, exist_ok=True)


CENARIO_ATIVO = ctx.CENARIO_ATIVO
TIMESTAMP_CENARIO = ctx.TIMESTAMP_CENARIO
_excel = ctx._excel
barramentos = ctx.barramentos
linhas = ctx.linhas
trafos = ctx.trafos
geracao = ctx.geracao
p_set_cargas = ctx.p_set_cargas

# 2. DESENHO GEOGRAFICO DA REDE
# ===========================================================================
CORES = {400: "#d62728", 220: "#2ca02c", 150: "#1f77b4"} 
ESPESSURA = {400: 1.4, 220: 1.0, 150: 0.7}
 
fig, ax = plt.subplots(figsize=(9, 13))
 
coords = barramentos.set_index("name")[["x", "y"]]
for _, linha in linhas.iterrows():
    if linha["bus0"] not in coords.index or linha["bus1"] not in coords.index:
        continue
    x0, y0 = coords.loc[linha["bus0"]]
    x1, y1 = coords.loc[linha["bus1"]]
    v = linha["v_nom"]
    ax.plot(
        [x0, x1], [y0, y1],
        color=CORES.get(v, "gray"),
        linewidth=ESPESSURA.get(v, 0.6),
        alpha=0.75,
        zorder=1,
    )
 
for v, cor in CORES.items():
    subset = barramentos[barramentos["v_nom"] == v]
    ax.scatter(
        subset["x"], subset["y"],
        s=14, color=cor, edgecolor="black", linewidth=0.3,
        zorder=2, label=f"{v} kV",
    )
 
ax.set_title("Rede Nacional de Transporte (RNT) - Portugal Continental\n"
             f"{len(barramentos)} barramentos | {len(linhas)} linhas | "
             f"{len(trafos)} transformadores",
             fontsize=12, fontweight="bold")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_aspect("equal", adjustable="box")
ax.grid(alpha=0.2)
 
legend_lines = [
    Line2D([0], [0], color=CORES[400], lw=2, label="400 kV"),
    Line2D([0], [0], color=CORES[220], lw=2, label="220 kV"),
    Line2D([0], [0], color=CORES[150], lw=2, label="150 kV"),
]
ax.legend(handles=legend_lines, loc="lower right", title="Nivel de tensao")
 
plt.tight_layout()
plt.savefig(RESULTADOS + "rede_rnt.png", dpi=300, bbox_inches="tight")
plt.savefig(RESULTADOS + "rede_rnt.svg", bbox_inches="tight")
plt.close(fig)
print("\nMapa da rede guardado em rede_rnt.png e rede_rnt.svg")
 
# ===========================================================================
# ---------------------------------------------------------------------------
# 3. Custos marginais assumidos (ordem de merito)
# ---------------------------------------------------------------------------
# Custos marginais fixos por tecnologia, definindo a ordem de merito do
# despacho economico. Nao sao precos de mercado calibrados por cenario:
# o problema de otimizacao linear compara apenas custos RELATIVOS entre
# tecnologias, pelo que uma escala unica aplicada a todas nao alteraria o
# despacho resultante.
#
#   Eolica e solar (0 EUR/MWh): sem custo de combustivel; o O&M variavel
#     residual e ignorado por simplificacao.
#   Hidrica (10 EUR/MWh): sem custo de combustivel, reflete o O&M variavel
#     e o custo de oportunidade da agua armazenada.
#   Biomassa (35 EUR/MWh): valor de referencia para co-combustao.
#   Fossil (gas natural): custo marginal de curto prazo, calculado por
#     cenario a partir do preco do gas, do preco do carbono, do fator de
#     emissao e da eficiencia da central:
#
#       SRMC = (preco_gas + fator_emissao * preco_carbono) / eficiencia + O&M
#
#     - Preco do gas (EUR/MWh termico, diario): lido de
#       dados/precos_gas_2024.csv. Usa o preco do ponto portugues (PT) e,
#       nos dias sem liquidez suficiente para formar preco, o ponto
#       espanhol (ES) como reserva, ja que os dois mercados estao
#       acoplados atraves do VIP Iberico. A coluna "origem" do CSV indica
#       qual foi usado em cada dia.
#     - Preco do carbono EU-ETS (EUR/tCO2, mensal): definido em
#       PRECO_CARBONO_MENSAL_2024, abaixo. O carbono varia muito mais
#       devagar que o gas, pelo que a resolucao mensal e suficiente.
#     - Fator de emissao, eficiencia e O&M: constantes definidas abaixo.
#
#   Importacao (100 EUR/MWh): irrelevante para o despacho, por estar
#     fixada em p_min_pu = p_max_pu = 1, mantida acima das restantes
#     apenas por convencao.
FATOR_EMISSAO_GAS = 0.202     # tCO2 / MWh termico
EFICIENCIA_CCGT = 0.55        # eficiencia tipica de central de ciclo combinado
OM_VARIAVEL_FOSSIL = 6.0      # EUR/MWh, O&M variavel de centrais a gas natural

# Preco do carbono EU-ETS por mes de 2024 (EUR/tCO2). Os 12 valores estao
# preenchidos para que o script funcione com qualquer instante do ano.
# Valor representativo do dia 15 de cada mes, lido do grafico publico de
# precos EU-ETS em resolucao semanal. Para simular outro ano, substituir
# estes valores pelos do periodo correspondente.
PRECO_CARBONO_MENSAL_2024 = {
    1: 65.94, 2: 56.75, 3: 62.72, 4: 68.52, 5: 73.15, 6: 68.23,
    7: 66.00, 8: 71.83, 9: 63.45, 10: 62.43, 11: 68.87, 12: 67.98,
}


def obter_preco_gas(data_alvo):
    """Le o preco medio diario do gas natural (EUR/MWh termico) do CSV
    local (precos_gas_2024.csv), gerado uma unica vez pelo script
    exportar_precos_gas.py a partir da API da REN Data Hub. O CSV ja
    tem a logica de reserva PT->ES aplicada (ver coluna 'origem')."""
    f_precos_gas = ctx.DADOS + "precos_gas_2024.csv"
    precos_gas = pd.read_csv(f_precos_gas, parse_dates=["data"]).set_index("data")

    data_alvo = pd.Timestamp(data_alvo).normalize()
    if data_alvo not in precos_gas.index:
        raise ValueError(
            f"Data {data_alvo.date()} nao encontrada em {f_precos_gas} - "
            f"o CSV tem de cobrir o ano do cenario escolhido."
        )
    linha = precos_gas.loc[data_alvo]
    return linha["preco_gas_eur_mwh"], linha["origem"], data_alvo


preco_gas, origem_gas, data_gas = obter_preco_gas(TIMESTAMP_CENARIO)
preco_carbono = PRECO_CARBONO_MENSAL_2024[TIMESTAMP_CENARIO.month]
if preco_carbono is None:
    raise ValueError(
        f"Falta preencher PRECO_CARBONO_MENSAL_2024[{TIMESTAMP_CENARIO.month}] "
        f"com o preco medio do carbono desse mes antes de correr o script."
    )

custo_fossil = (preco_gas + FATOR_EMISSAO_GAS * preco_carbono) / EFICIENCIA_CCGT \
    + OM_VARIAVEL_FOSSIL

print(f"\nCusto marginal do fossil calculado para {CENARIO_ATIVO}:")
print(f"  Preco do gas: {preco_gas:.2f} EUR/MWh ({origem_gas}, dado de {data_gas.date()})")
print(f"  Preco do carbono (media de {TIMESTAMP_CENARIO.month}/2024): {preco_carbono:.2f} EUR/tCO2")
print(f"  Custo marginal fossil resultante: {custo_fossil:.2f} EUR/MWh")

CUSTOS_MARGINAIS = {
    "wind":    0.0,
    "solar":   0.0,
    "hydro":   10.0,
    "biomass": 35.0,
    "fossil":  round(custo_fossil, 2),
    "import":  100.0,
}
n.generators["marginal_cost"] = n.generators["carrier"].map(CUSTOS_MARGINAIS).fillna(0.0)

 
# ===========================================================================
# 4. FATOR DE CAPACIDADE RENOVAVEL VIA ATLITE (ERA5) - OPCIONAL
# ===========================================================================
# Ver CORRER_ATLITE na seccao de OPCOES DE SIMULACAO, no topo do ficheiro.
if CORRER_ATLITE:
    import atlite
 
    DATA_CENARIO = TIMESTAMP_CENARIO.strftime("%Y-%m-%d")
    HORA_PONTA = TIMESTAMP_CENARIO.strftime("%H:%M")
 
    DATA_INICIO = (TIMESTAMP_CENARIO - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    DATA_FIM = (TIMESTAMP_CENARIO + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
 
    BBOX = dict(x0=-9.6, y0=36.9, x1=-6.1, y1=42.2)
 
    TURBINA = "Vestas_V112_3MW"
    PAINEL = "CSi"
    INCLINACAO = 35 
    AZIMUTE = 180   
 
    CUTOUT_PATH = rf"{CACHE}portugal_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.nc"

    cutout = atlite.Cutout(
        path=CUTOUT_PATH,
        module="era5",
        x=slice(BBOX["x0"], BBOX["x1"]),
        y=slice(BBOX["y0"], BBOX["y1"]),
        time=slice(DATA_INICIO, DATA_FIM),
    )
    if not os.path.exists(CUTOUT_PATH):
        cutout.prepare()
 
    cf_eolica = cutout.wind(turbine=TURBINA, capacity_factor_timeseries=True)
    cf_solar = cutout.pv(
        panel=PAINEL,
        orientation={"slope": INCLINACAO, "azimuth": AZIMUTE},
        capacity_factor_timeseries=True,
    )
 
    timestamp_ponta = pd.Timestamp(f"{DATA_CENARIO} {HORA_PONTA}")
    cf_eolica_ponta = cf_eolica.sel(time=timestamp_ponta, method="nearest")
    cf_solar_ponta = cf_solar.sel(time=timestamp_ponta, method="nearest")
 
    geracao["x"] = geracao["bus"].map(barramentos.set_index("name")["x"])
    geracao["y"] = geracao["bus"].map(barramentos.set_index("name")["y"])
 
    def cf_mais_proximo(cf_grid, lon, lat):
        return float(cf_grid.sel(x=lon, y=lat, method="nearest").values)
 
    for _, gen in geracao[geracao["Carrier"] == "wind"].iterrows():
        n.generators.loc[gen["name"], "p_max_pu"] = cf_mais_proximo(
            cf_eolica_ponta, gen["x"], gen["y"]
        )
 
    for _, gen in geracao[geracao["Carrier"] == "solar"].iterrows():
        n.generators.loc[gen["name"], "p_max_pu"] = cf_mais_proximo(
            cf_solar_ponta, gen["x"], gen["y"]
        )
 
    n_eolica = (geracao["Carrier"] == "wind").sum()
    n_solar = (geracao["Carrier"] == "solar").sum()
    print(f"\nCenario: {CENARIO_ATIVO}, {DATA_CENARIO} ~{HORA_PONTA}")
    print(f"p_max_pu (estatico) atribuido a {n_eolica} geradores eolicos "
          f"e {n_solar} geradores solares.")
    print("p_max_pu medio eolica:",
          n.generators.loc[geracao[geracao['Carrier']=='wind']['name'], 'p_max_pu'].mean())
    print("p_max_pu medio solar:",
          n.generators.loc[geracao[geracao['Carrier']=='solar']['name'], 'p_max_pu'].mean())
 
    F_REDE_CENARIO = rf"{CACHE}rnt_portugal_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.nc"
    n.export_to_netcdf(F_REDE_CENARIO)
    print(f"Rede guardada em {F_REDE_CENARIO}")
 
else:
    print("\n(Bloco atlite desativado - muda CORRER_ATLITE para True para ativar)")


def diagnosticar_infeasibility(n, snapshot=None):
    """Diagnostica a causa de uma otimizacao (n.optimize) infeasible.
    O metodo n.model.format_infeasibilities() do tutorial oficial do PyPSA
    so funciona com Gurobi ou Xpress (usam o calculo de IIS - Irreducible
    Inconsistent Set - nativo desses solvers). O HiGHS, que e gratuito e
    sem licenca, ainda nao suporta isto via linopy. Por isso esta funcao:
      1. Se o gurobipy estiver instalado E houver licenca valida (inclui
         licencas academicas gratuitas), resolve outra vez com Gurobi so
         para obter o IIS exato.
      2. Caso contrario, corre diagnosticos manuais validos com qualquer
         solver: barramentos isolados com carga mas sem geracao
         alcancavel, balanco global geracao vs carga, e geradores com
         bounds contraditorios (p_min_pu > p_max_pu).
    """
    import networkx as nx

    if snapshot is None:
        snapshot = n.snapshots[0]

    print("\n" + "-" * 60)
    print("DIAGNOSTICO DE INFEASIBILITY")
    print("-" * 60)

    # -- Diagnostico manual 1: barramentos isolados com carga ------------
    G = nx.Graph()
    G.add_nodes_from(n.buses.index)
    G.add_edges_from(zip(n.lines.bus0, n.lines.bus1))
    G.add_edges_from(zip(n.transformers.bus0, n.transformers.bus1))
    if len(n.links):
        G.add_edges_from(zip(n.links.bus0, n.links.bus1))

    carga_por_bus = n.loads_t.p_set.loc[snapshot].groupby(n.loads.bus).sum() \
        if not n.loads_t.p_set.empty else n.loads.set_index("bus")["p_set"]
    carga_por_bus = carga_por_bus.reindex(n.buses.index, fill_value=0.0)

    p_max = n.generators.p_nom.copy()
    if not n.generators_t.p_max_pu.empty:
        pmpu = n.generators_t.p_max_pu.loc[snapshot]
        for gen in n.generators.index:
            fator = pmpu[gen] if gen in pmpu.index else n.generators.at[gen, "p_max_pu"]
            p_max[gen] = n.generators.at[gen, "p_nom"] * fator
    else:
        p_max = n.generators.p_nom * n.generators.get("p_max_pu", 1.0)
    capacidade_por_bus = p_max.groupby(n.generators.bus).sum().reindex(
        n.buses.index, fill_value=0.0
    )

    problemas_encontrados = False
    for componente in nx.connected_components(G):
        carga_componente = carga_por_bus.loc[list(componente)].sum()
        capacidade_componente = capacidade_por_bus.loc[list(componente)].sum()
        if carga_componente > 0 and capacidade_componente < carga_componente:
            problemas_encontrados = True
            print(f"\n[ILHA/COMPONENTE DESLIGADA OU SUBALIMENTADA]")
            print(f"  Barramentos ({len(componente)}): "
                  f"{sorted(componente)[:10]}{'...' if len(componente) > 10 else ''}")
            print(f"  Carga total nesta componente:      {carga_componente:,.1f} MW")
            print(f"  Capacidade maxima disponivel aqui:  {capacidade_componente:,.1f} MW")
            print(f"  Defice:                              "
                  f"{carga_componente - capacidade_componente:,.1f} MW")
            if capacidade_componente == 0:
                print("  -> Esta componente NAO TEM NENHUM gerador com "
                      "capacidade disponivel neste snapshot.")

    if not problemas_encontrados:
        print("\nNao ha componentes da rede isoladas/subalimentadas. "
              "A verificar balanco global e bounds dos geradores...")
        carga_total = carga_por_bus.sum()
        capacidade_total = capacidade_por_bus.sum()
        print(f"  Carga total do snapshot:       {carga_total:,.1f} MW")
        print(f"  Capacidade maxima total (rede): {capacidade_total:,.1f} MW")
        if capacidade_total < carga_total:
            print("  -> DEFICE GLOBAL: a rede toda nao tem capacidade "
                  "suficiente para cobrir a carga neste snapshot.")
            problemas_encontrados = True

        p_min_pu = n.generators.get("p_min_pu", 0.0)
        p_max_pu = n.generators.get("p_max_pu", 1.0)
        bounds_maus = n.generators[p_min_pu > p_max_pu]
        if len(bounds_maus):
            problemas_encontrados = True
            print(f"\n  -> {len(bounds_maus)} gerador(es) com p_min_pu > "
                  f"p_max_pu (bounds contraditorios, impossivel satisfazer):")
            print(bounds_maus[["bus", "carrier"]].to_string())

    if not problemas_encontrados:
        print("\nNenhuma causa obvia encontrada pelos diagnosticos manuais. "
              "O gurobipy, com licenca academica gratuita "
              "(https://www.gurobi.com/academia/), permite obter o IIS exato. "
              "Em alternativa, reduzir a rede ate isolar a restricao "
              "problematica.")
    print("-" * 60)


def resolver_com_fallback_gurobi(n):
    """Tenta resolver com HiGHS (gratuito, sem licenca). Se ficar infeasible,
    corre o diagnostico manual e, se o gurobipy estiver instalado e houver
    licenca valida (inclui licencas academicas gratuitas), tenta resolver
    outra vez com Gurobi antes de desistir."""
    status, condicao = n.optimize(solver_name="highs")

    if condicao == "optimal":
        return status, condicao

    print(f"\nHiGHS nao encontrou solucao otima (condicao: {condicao}).")
    diagnosticar_infeasibility(n)

    try:
        import gurobipy  # noqa: F401
        print("\ngurobipy encontrado - a tentar resolver com Gurobi...")
        try:
            status, condicao = n.optimize(solver_name="gurobi")
        except Exception as e:
            # Apanha erros de ligacao/licenca (ex: 502 Bad Gateway ao
            # autenticar no servidor WLS do Gurobi), nao so problemas do
            # proprio problema de otimizacao - evita crash do script.
            print(f"\nERRO ao tentar resolver com Gurobi: {e}")
            print("Isto e normalmente um problema de rede ou de licenca "
                  "(ex: servidor de licencas do Gurobi indisponivel "
                  "temporariamente), nao um erro do modelo. Tenta outra "
                  "vez mais tarde, ou verifica a ligacao a token.gurobi.com.")
            print("\nA manter o resultado (infeasible) obtido pelo HiGHS.")
            return status, condicao

        if condicao == "optimal":
            print("Gurobi encontrou solucao otima.")
        else:
            print(f"Gurobi tambem nao encontrou solucao (condicao: {condicao}).")
            try:
                print(n.model.format_infeasibilities())
            except Exception:
                pass
    except ImportError:
        print("gurobipy nao esta instalado - sem fallback disponivel. "
              "Requer 'pip install gurobipy' e uma licenca, academica "
              "gratuita ou paga (https://www.gurobi.com/academia/).")

    return status, condicao


# ===========================================================================
# 5. DESPACHO ECONOMICO (OPF) COM COMPENSACAO ITERATIVA DE PERDAS
# ===========================================================================
# Ao contrario do despacho imposto (ficheiro topologia.py, versao "despacho
# real"), esta versao deixa o solver DECIDIR o despacho, dado o custo
# marginal assumido por tecnologia (Seccao 3) e a disponibilidade
# renovavel calculada pelo atlite/ERA5 (Seccao 4, p_max_pu).
#
# O OPF linear (n.optimize) NAO modela perdas nas linhas (usa apenas a
# reatancia x, ignora a resistencia r). Isto significa que o despacho
# escolhido pode ficar ligeiramente aquem do necessario para cobrir carga
# + perdas reais. Para corrigir isto, aplica-se uma COMPENSACAO ITERATIVA:
#   1. Otimiza o despacho (OPF) para a carga atual.
#   2. Fixa esse despacho e corre o Power Flow nao linear (AC) para medir
#      as perdas REAIS nas linhas.
#   3. Adiciona essas perdas a carga total (proporcionalmente aos
#      barramentos existentes) e volta ao passo 1.
#   4. Repete ate as perdas estabilizarem (variacao < TOL_PERDAS_MW entre
#      iteracoes consecutivas) ou atingir o numero maximo de iteracoes.
#
# Se o OPF ficar infeasible nalguma iteracao (ver nota metodologica no
# topologia.py "despacho real" - pode acontecer por congestionamento real
# de alguma linha), corre-se o diagnostico automatico e tenta-se o Gurobi
# como fallback (requer 'pip install gurobipy' e licenca, academica ou
# paga - sem isso, o script para e reporta o diagnostico obtido).
# Ver CORRER_OPF, MAX_ITER_PERDAS, TOL_PERDAS_MW, DISTRIBUIR_SLACK e
# CARRIERS_EXCLUIDOS_DO_SLACK na seccao de OPCOES DE SIMULACAO, no topo
# do ficheiro.




def executar_ciclo_opf_perdas(n, p_set_cargas_base, max_iter=MAX_ITER_PERDAS,
                               tol_mw=TOL_PERDAS_MW, verbose=True):
    """Executa o ciclo completo de OPF + compensacao iterativa de perdas,
    tal como descrito acima, e devolve (perdas_final, despacho_por_tecnologia,
    convergiu). Extraida para funcao propria para poder ser chamada
    repetidamente pela calibracao de custos marginais (Seccao 5.1), sem
    duplicar esta logica.

    NAO faz a reportagem final (tensoes, carregamento, exportacao) nem
    decide os custos marginais - isso e responsabilidade de quem chama.
    Usa sempre os custos marginais ja atribuidos a n.generators['marginal_cost']
    no momento em que e chamada."""
    perdas_estimadas = 0.0
    perdas_final = None
    despacho_final = None

    for iteracao in range(1, max_iter + 1):
        if verbose:
            print(f"\n--- Iteracao {iteracao}/{max_iter} "
                  f"(perdas assumidas: {perdas_estimadas:.2f} MW) ---")

        fator_extra = 1.0 + (perdas_estimadas / p_set_cargas_base.sum()
                              if p_set_cargas_base.sum() > 0 else 0.0)
        # .loc[] com o indice explicito de p_set_cargas_base (as cargas
        # domesticas de cargas.csv) - NAO usar n.loads["p_set"] = ... aqui,
        # isso tocaria tambem na carga de exportacao (Seccao 9.2 do
        # rede_base.py), cujo p_set deve manter-se sempre fixo, sem ser
        # reescalado pelas perdas assumidas nesta iteracao.
        n.loads.loc[p_set_cargas_base.index, "p_set"] = p_set_cargas_base * fator_extra

        status, condicao = resolver_com_fallback_gurobi(n)
        if condicao != "optimal":
            if verbose:
                print("\nOPF nao encontrou solucao otima nesta tentativa "
                      "de calibracao - a devolver como nao convergido.")
            return None, None, False

        despacho_final = n.generators_t.p.iloc[0].groupby(n.generators.carrier).sum()
        if verbose:
            print("Despacho obtido por tecnologia (MW):")
            print(despacho_final.round(1))

        n.generators["p_set"] = n.generators_t.p.iloc[0]

        pesos_slack_todos = n.generators["p_set"].copy()
        pesos_slack_todos[n.generators["carrier"].isin(CARRIERS_EXCLUIDOS_DO_SLACK)] = 0.0

        convergiu, capados = resolver_pf_respeitando_capacidade(
            n, pesos_slack_todos, DISTRIBUIR_SLACK, verbose=verbose
        )

        # IMPORTANTE: NaN, nao 0.0 - ver nota completa na versao original
        # desta seccao. Um 0.0 aqui prende os geradores a zero na proxima
        # chamada a n.optimize().
        n.generators["p_set"] = float("nan")

        if not convergiu:
            if verbose:
                print("\nPower flow AC nao convergiu nesta tentativa de "
                      "calibracao - a devolver como nao convergido.")
            return None, None, False

        perdas_nova = (n.lines_t.p0.iloc[0] + n.lines_t.p1.iloc[0]).sum()
        if verbose:
            print(f"Perdas reais medidas (power flow AC): {perdas_nova:.2f} MW")

        if abs(perdas_nova - perdas_estimadas) < tol_mw:
            if verbose:
                print(f"\nPerdas estabilizaram (variacao < {tol_mw} MW). "
                      f"Convergido em {iteracao} iteracao(oes).")
            perdas_final = perdas_nova
            return perdas_final, despacho_final, True

        perdas_estimadas = perdas_nova

    if verbose:
        print(f"\nAVISO: atingido o numero maximo de iteracoes ({max_iter}) "
              f"sem as perdas estabilizarem totalmente.")
    return perdas_estimadas, despacho_final, True


# ===========================================================================
# 5.1 CALIBRACAO DE CUSTOS MARGINAIS (OPCIONAL)
# ===========================================================================
# Em vez de usar o custo marginal do fossil calculado pela formula SRMC
# (Seccao 3), esta seccao PROCURA o custo que faz o despacho do OPF
# aproximar-se o mais possivel do despacho REAL reportado pela REN para o
# mesmo instante. Serve para investigar ate que ponto a diferenca entre o
# despacho real e o despacho otimizado se deve ao custo assumido, ou a
# outras restricoes que o modelo nao capta (nomeadamente restricoes de
# transporte).
#
# NOTA METODOLOGICA IMPORTANTE: esta calibracao e
# EXPLORATORIA, distinta da analise principal. Os custos que dai resultam
# nao substituem os custos justificados pela literatura na Seccao 3 do
# presente script -
# um custo "calibrado" so tem sentido economico se cair dentro de uma gama
# plausivel; se sair negativo, ou extremo, isso e evidencia CONTRA a
# hipotese de que o preco explica a diferenca, nao a favor.
#
# FASE 1 (sempre executada primeiro): pesquisa binaria, so no custo do
# fossil, assumindo que despacho_fossil(custo) e monotona decrescente -
# quanto mais caro, menos fossil o OPF escolhe.
# FASE 2 (so corre se a Fase 1 nao aproximar o suficiente): otimizacao em
# 3 dimensoes (fossil, hidrica, biomassa) via scipy.optimize.minimize,
# minimizando a soma dos erros absolutos face ao despacho real das tres
# tecnologias em simultaneo. Eolica/solar mantidas a 0 (ja justificado);
# importacao mantida a 100 (sem efeito no despacho, ja justificado).
# Ver CALIBRAR_CUSTO_FOSSIL e as constantes associadas na seccao de
# OPCOES DE SIMULACAO, no topo do ficheiro.


def obter_despacho_real_por_tecnologia(_excel, timestamp):
    """Repete exatamente a mesma extracao do despacho real do topologia.py
    (Seccao 6) - ver esse ficheiro para a logica original. Usada aqui so
    para comparacao, nunca para impor nada a rede."""
    fossil_real = (
        _excel.loc[timestamp, "Gás Natural - Ciclo Combinado"]
        + _excel.loc[timestamp, "Gás natural - Cogeração"]
        + _excel.loc[timestamp, "Carvão"]
        + _excel.loc[timestamp, "Outra Térmica"]
    )
    return {
        "hydro": _excel.loc[timestamp, "Hídrica"],
        "biomass": _excel.loc[timestamp, "Biomassa"],
        "fossil": fossil_real,
    }


def calibrar_custo_fossil_bissecao(n, p_set_cargas_base, fossil_real):
    """FASE 1: pesquisa binaria no custo do fossil. Devolve
    (custo_encontrado, fossil_obtido, convergiu_bem)."""
    print("\n" + "-" * 60)
    print("CALIBRACAO (Fase 1) - pesquisa binaria no custo do fossil")
    print("-" * 60)
    print(f"Despacho real do fossil, alvo desta calibracao: {fossil_real:.1f} MW")

    # Custo SRMC deste cenario, calculado pela equacao (41) e guardado
    # antes de a pesquisa comecar a sobrepo-lo. Cada tentativa escreve o
    # seu proprio valor em marginal_cost, e sem reposicao o custo do
    # fossil ficaria, no fim desta fase, no ultimo valor testado - que a
    # Fase 2 leria depois como ponto de partida, em vez do valor
    # justificado pela literatura. E reposto antes de qualquer return
    # desta funcao; o
    # custo escolhido pela calibracao e aplicado a rede pelo chamador.
    custo_fossil_srmc = n.generators.loc[
        n.generators.carrier == "fossil", "marginal_cost"
    ].iloc[0]

    custo_min, custo_max = CUSTO_MIN_BISSECAO, CUSTO_MAX_BISSECAO
    melhor_custo, melhor_fossil, melhor_erro = None, None, float("inf")

    for tentativa in range(1, MAX_ITER_BISSECAO + 1):
        custo_teste = (custo_min + custo_max) / 2
        n.generators.loc[n.generators.carrier == "fossil", "marginal_cost"] = custo_teste

        perdas, despacho, convergiu = executar_ciclo_opf_perdas(
            n, p_set_cargas_base, verbose=False
        )
        if not convergiu:
            # Nao convergir aqui e tipicamente sintoma de o custo estar
            # muito proximo do de outra tecnologia,
            # despoletando saturacao de capacidade na redistribuicao do
            # Slack. Trata-se como "custo baixo demais" (avanca custo_min
            # para cima), o mesmo lado de onde esta instabilidade tende a
            # surgir - critico para GARANTIR PROGRESSO: sem isto, o
            # proximo ponto medio seria identico a este, e o ciclo ficaria
            # preso a testar sempre o mesmo valor ate esgotar as
            # tentativas, sem nunca avancar.
            print(f"  Tentativa {tentativa}: custo={custo_teste:.2f} EUR/MWh "
                  f"-> nao convergiu, a tratar como custo baixo demais.")
            custo_min = custo_teste
            continue

        fossil_obtido = despacho.get("fossil", 0.0)
        erro = fossil_obtido - fossil_real
        print(f"  Tentativa {tentativa}: custo={custo_teste:.2f} EUR/MWh "
              f"-> fossil={fossil_obtido:.1f} MW (erro={erro:+.1f} MW)")

        if abs(erro) < melhor_erro:
            melhor_custo, melhor_fossil, melhor_erro = custo_teste, fossil_obtido, abs(erro)

        if abs(erro) < TOL_BISSECAO_MW:
            print(f"\nConvergiu: custo={custo_teste:.2f} EUR/MWh reproduz "
                  f"o despacho real do fossil dentro de {TOL_BISSECAO_MW} MW.")
            n.generators.loc[n.generators.carrier == "fossil", "marginal_cost"] = custo_fossil_srmc
            return custo_teste, fossil_obtido, True

        if erro > 0:  # obtido mais do que o real -> custo esta baixo demais
            custo_min = custo_teste
        else:  # obtido menos do que o real -> custo esta alto demais
            custo_max = custo_teste

    print(f"\nNao convergiu dentro da tolerancia em {MAX_ITER_BISSECAO} "
          f"tentativas. Melhor resultado: custo={melhor_custo:.2f} EUR/MWh, "
          f"fossil={melhor_fossil:.1f} MW (erro={melhor_erro:.1f} MW).")
    n.generators.loc[n.generators.carrier == "fossil", "marginal_cost"] = custo_fossil_srmc
    return melhor_custo, melhor_fossil, False


def calibrar_custos_multiplos(n, p_set_cargas_base, despacho_real):
    """FASE 2: otimizacao em 3 dimensoes (fossil, hidrica, biomassa) via
    scipy.optimize.minimize. So chamada se a Fase 1 nao aproximar o
    suficiente. Devolve um dicionario {carrier: custo_encontrado}."""
    from scipy.optimize import minimize

    print("\n" + "-" * 60)
    print("CALIBRACAO (Fase 2) - otimizacao conjunta em 3 dimensoes")
    print("-" * 60)
    print("AVISO: esta fase e lenta - cada avaliacao corre o ciclo OPF+perdas")
    print("completo. Pode demorar vários minutos.")

    carriers_calibrar = ["fossil", "hydro", "biomass"]
    avaliacoes = []

    def erro_total(custos):
        for carrier, custo in zip(carriers_calibrar, custos):
            n.generators.loc[n.generators.carrier == carrier, "marginal_cost"] = custo

        perdas, despacho, convergiu = executar_ciclo_opf_perdas(
            n, p_set_cargas_base, verbose=False
        )
        if not convergiu:
            avaliacoes.append((dict(zip(carriers_calibrar, custos)), None, float("inf")))
            return 1e9  # penalizacao forte para nao-convergencia

        erro = sum(
            abs(despacho.get(c, 0.0) - despacho_real[c]) for c in carriers_calibrar
        )
        avaliacoes.append((dict(zip(carriers_calibrar, custos)), despacho.to_dict(), erro))
        print(f"  custos={[round(c, 1) for c in custos]} -> erro_total={erro:.1f} MW")
        return erro

    custos_iniciais = [
        n.generators.loc[n.generators.carrier == c, "marginal_cost"].iloc[0]
        for c in carriers_calibrar
    ]
    limites = [(CUSTO_MIN_BISSECAO, CUSTO_MAX_BISSECAO)] * 3

    resultado = minimize(
        erro_total, custos_iniciais, method="Nelder-Mead", bounds=limites,
        options={"maxiter": 100, "xatol": 1.0, "fatol": 1.0},
    )

    custos_finais = dict(zip(carriers_calibrar, resultado.x))
    print(f"\nMelhor combinacao encontrada: "
          f"{ {k: round(v, 2) for k, v in custos_finais.items()} }")
    print(f"Erro total (soma dos desvios absolutos): {resultado.fun:.1f} MW")

    # Localizar, dentro de todas as avaliacoes reais feitas durante a
    # procura, aquela com o menor erro - e nao confiar so em resultado.x,
    # que pode nao corresponder exatamente a nenhuma avaliacao concreta
    # (o Nelder-Mead pode devolver um ponto interpolado). Ignora avaliacoes
    # que nao convergiram (despacho None).
    avaliacoes_validas = [a for a in avaliacoes if a[1] is not None]
    if avaliacoes_validas:
        melhor_custos, melhor_despacho, melhor_erro = min(
            avaliacoes_validas, key=lambda a: a[2]
        )
        print(f"\nDespacho obtido no melhor ponto encontrado, "
              f"comparado com o despacho real:")
        print(f"{'Tecnologia':<10} {'Real (MW)':>12} {'Obtido (MW)':>14} "
              f"{'Diferenca (MW)':>16}")
        for carrier in carriers_calibrar:
            real = despacho_real[carrier]
            obtido = melhor_despacho.get(carrier, 0.0)
            print(f"{carrier:<10} {real:>12.1f} {obtido:>14.1f} "
                  f"{obtido - real:>+16.1f}")
    else:
        print("\nAVISO: nenhuma avaliacao da Fase 2 convergiu - sem "
              "despacho valido para comparar.")

    return custos_finais



if CORRER_OPF:
    print("\n" + "=" * 60)
    print("DESPACHO ECONOMICO (OPF) + COMPENSACAO ITERATIVA DE PERDAS")
    print("(custos marginais SRMC, Seccao 3 - execucao de referencia)")
    print("=" * 60)

    perdas_final, despacho_final, convergiu = executar_ciclo_opf_perdas(
        n, p_set_cargas, verbose=True
    )
    if not convergiu:
        raise SystemExit(
            "\nOPF/Power flow nao convergiu na execucao final - ver "
            "diagnostico acima."
        )

    print(f"\nCarga total (com perdas incorporadas): "
          f"{n.loads.p_set.sum():,.1f} MW")
    print(f"Perdas totais nas linhas (final): {perdas_final:.2f} MW")

    print("\nTensoes nos barramentos (p.u.) - resumo:")
    print(n.buses_t.v_mag_pu.T.describe().round(4))

    print("\nCarregamento de linhas e transformadores (% de s_nom) - top 10:")
    carregamento = pd.concat([
        (n.lines_t.p0.abs().iloc[0] / n.lines.s_nom * 100),
        (n.transformers_t.p0.abs().iloc[0] / n.transformers.s_nom * 100),
    ]).sort_values(ascending=False)
    print(carregamento.head(10).round(2))

    F_RESULTADO_PF = rf"{CACHE}rnt_portugal_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}_OPF_resultado.nc"
    n.export_to_netcdf(F_RESULTADO_PF)
    print(f"\nRede com resultados do OPF+PF guardada em {F_RESULTADO_PF}")

    # -----------------------------------------------------------------
    # Calibracao (opcional) - corre DEPOIS da execucao de referencia
    # acima, nunca a substituindo. Os mapas, tensoes, carregamento e a
    # exportacao acima referem-se sempre a versao SRMC - a calibracao
    # serve so para efeitos de comparacao, apresentada de seguida.
    # -----------------------------------------------------------------
    if CALIBRAR_CUSTO_FOSSIL:
        despacho_real_calibracao = obter_despacho_real_por_tecnologia(_excel, TIMESTAMP_CENARIO)

        custo_fossil_calibrado, fossil_obtido_fase1, convergiu_fase1 = \
            calibrar_custo_fossil_bissecao(n, p_set_cargas, despacho_real_calibracao["fossil"])

        erro_pct_fase1 = (
            abs(fossil_obtido_fase1 - despacho_real_calibracao["fossil"])
            / despacho_real_calibracao["fossil"] * 100
            if despacho_real_calibracao["fossil"] > 0 else float("inf")
        )
        print(f"\nErro da Fase 1: {erro_pct_fase1:.1f}% "
              f"(limiar para avançar para a Fase 2: {LIMIAR_APROXIMACAO_PCT}%)")

        if erro_pct_fase1 <= LIMIAR_APROXIMACAO_PCT:
            print("\nFase 1 aproximou o suficiente - a usar este custo.")
            CUSTOS_MARGINAIS["fossil"] = custo_fossil_calibrado
            n.generators.loc[n.generators.carrier == "fossil", "marginal_cost"] = custo_fossil_calibrado
        else:
            print("\nFase 1 nao aproximou o suficiente - a avancar para a Fase 2.")
            custos_calibrados = calibrar_custos_multiplos(n, p_set_cargas, despacho_real_calibracao)
            for carrier, custo in custos_calibrados.items():
                CUSTOS_MARGINAIS[carrier] = custo
                n.generators.loc[n.generators.carrier == carrier, "marginal_cost"] = custo

        # Execucao final, oficial, com os custos ja calibrados - repete o
        # ciclo completo (nao reaproveita nenhuma avaliacao da procura),
        # para garantir um resultado limpo e diretamente comparavel ao
        # da execucao SRMC acima.
        print("\n" + "-" * 60)
        print("EXECUCAO FINAL COM CUSTOS CALIBRADOS")
        print("-" * 60)
        perdas_calibrado, despacho_calibrado, convergiu_calibrado = executar_ciclo_opf_perdas(
            n, p_set_cargas, verbose=True
        )

        print("\n" + "=" * 60)
        print("COMPARACAO: DESPACHO REAL vs SRMC vs CALIBRADO")
        print("=" * 60)
        print(f"{'Tecnologia':<10}{'Real (MW)':>12}{'SRMC (MW)':>12}{'Calibrado (MW)':>16}")
        for carrier in ["hydro", "fossil", "biomass", "wind", "solar", "import"]:
            real = despacho_real_calibracao.get(carrier, float("nan"))
            srmc = despacho_final.get(carrier, 0.0)
            calib = despacho_calibrado.get(carrier, 0.0) if convergiu_calibrado else float("nan")
            print(f"{carrier:<10}{real:>12.1f}{srmc:>12.1f}{calib:>16.1f}")

        print(f"\nPerdas - SRMC: {perdas_final:.2f} MW | "
              f"Calibrado: {perdas_calibrado if convergiu_calibrado else float('nan'):.2f} MW")

        if convergiu_calibrado:
            F_RESULTADO_CALIB = rf"{CACHE}rnt_portugal_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}_OPF_calibrado.nc"
            n.export_to_netcdf(F_RESULTADO_CALIB)
            print(f"\nRede com resultados calibrados guardada em {F_RESULTADO_CALIB}")
        else:
            print("\nAVISO: a execucao final calibrada nao convergiu - "
                  "sem ficheiro calibrado exportado.")
else:
    print("\n(Bloco OPF desativado - muda CORRER_OPF para True para ativar)")


# ===========================================================================
# 6. VISUALIZACAO NATIVA DO PYPSA (CONGESTIONAMENTO + ESTATISTICAS)
# ===========================================================================
# METODOLOGIA: em vez de depender so do mapa
# desenhado manualmente (Seccao 2, matplotlib puro), esta seccao usa
# explicitamente as ferramentas de visualizacao INCLUIDAS no PyPSA -
# n.plot() (mapa) e o modulo n.statistics (metricas/graficos) - que ja
# sabem posicionar a rede a partir das coordenadas dos barramentos e
# mapear resultados (carregamento, despacho) diretamente em
# cores/espessuras, sem reimplementar essa logica a mao. Complementa, nao
# substitui, o mapa da Seccao 2. Identica a Seccao 5 do topologia.py,
# aqui aplicada ao despacho por OPF em vez do despacho real imposto -
# permite comparar visualmente os dois metodos.
#
# A assinatura de n.plot() varia entre versoes do PyPSA. O try/except
# abaixo garante que uma eventual incompatibilidade nao interrompe a
# execucao do script.
if CORRER_OPF and convergiu:
    print("\n" + "=" * 60)
    print("VISUALIZACAO NATIVA DO PYPSA")
    print("=" * 60)

    # -- 13.1 Mapa de congestionamento (n.plot) --------------------------
    # Cor E espessura das linhas proporcionais ao carregamento (% de
    # s_nom) - visualiza diretamente os pontos de congestionamento ja
    # da rede. Os barramentos sao desenhados como GRAFICOS
    # CIRCULARES (pie charts) com a reparticao da producao REAL por
    # tecnologia nesse ponto (n.generators_t.p, nao o p_set imposto - ver
    # nota metodologica da Seccao 4 do topologia.py sobre a diferenca
    # entre os dois - nao confundir com a Seccao 5 deste ficheiro, que
    # e sobre o OPF, um tema diferente),
    # aproveitando que n.plot() interpreta automaticamente um bus_sizes
    # com indice duplo (barramento, carrier) desta forma - funcionalidade
    # nativa do PyPSA (ver User Guide, Maps (Static) > Input data), em
    # vez de continuarmos a desenhar todos os barramentos como pontos
    # pretos uniformes.
    try:
        carregamento_pct_mapa = (n.lines_t.p0.abs().iloc[0] / n.lines.s_nom * 100)

        # Producao real por (barramento, tecnologia) - so valores >0.01 MW,
        # para nao desenhar fatias residuais de tecnologias com 0 MW nesse
        # ponto (ex: geradores de importacao com p_set=0 neste cenario).
        # A ausencia de uma tecnologia no mapa corresponde a producao ~0
        # em todo o cenario (por exemplo, solar as 19h45 de Janeiro, sem
        # irradiancia), e nao a uma falha de representacao.
        eb_geracao = (
            n.generators_t.p.iloc[0]
            .groupby([n.generators.bus, n.generators.carrier])
            .sum()
        )
        eb_geracao = eb_geracao[eb_geracao > 0.01]

        for c in n.generators.carrier.unique():
            total_c = n.generators_t.p.iloc[0][n.generators.carrier == c].sum()
            if total_c <= 0.01:
                print(f"  (nota: '{c}' nao aparece no mapa - producao total "
                      f"neste cenario e ~0 MW: {total_c:.3f} MW)")

        # Escala UNICA e simples, sem piso minimo nem qualquer condicao -
        # so uma multiplicacao direta de todos os valores pela mesma
        # constante. Isto NUNCA altera as fatias/proporcoes (nem dentro
        # de um circulo, nem entre circulos diferentes): A/B = (A*k)/(B*k)
        # e sempre verdade, para qualquer k. So reduz o tamanho geral.
        # Sem escala, o maior circulo domina o mapa por completo. Este
        # valor foi ajustado empiricamente para uma leitura equilibrada.
        ESCALA_CIRCULOS = 0.00003
        eb_geracao_visual = eb_geracao * ESCALA_CIRCULOS

        # Cores intuitivas por tecnologia (substitui a paleta tab10
        # atribuida automaticamente por n.sanitize(), que nao tem
        # associacao intuitiva nenhuma - ex: vermelho para hidrica).
        CORES_TECNOLOGIA = {
            "hydro":   "#0072B2",  # azul - agua
            "wind":    "#56B4E9",  # azul claro - vento
            "solar":   "#F0E442",  # amarelo - sol
            "biomass": "#2CA02C",  # verde - organico
            "fossil":  "#4D4D4D",  # cinzento escuro - fumo/carbono
            "import":  "#9467BD",  # roxo - distinto das tecnologias de producao
        }
        for carrier, cor in CORES_TECNOLOGIA.items():
            if carrier in n.carriers.index:
                n.carriers.at[carrier, "color"] = cor

        # Cor das linhas: gradiente verde->vermelho FIXO entre 0-100% (ja
        # nao se estica para alem disso), mais uma cor UNICA e distinta
        # (magenta/rosa choque) para qualquer linha ACIMA de 100% - torna
        # imediatamente visivel quais as linhas sobrecarregadas, em vez
        # de ficarem "escondidas" como um vermelho-ainda-mais-escuro
        # dentro do mesmo gradiente.
        import matplotlib.colors as mcolors

        COR_SOBRECARGA = "#FF00FF"  # magenta - destaca-se do verde/amarelo/vermelho do gradiente
        ESPESSURA_NORMAL = 1.2
        ESPESSURA_SOBRECARGA = 3.5  # bem mais grossa - garante visibilidade mesmo em trocos curtos
        norm_0_100 = plt.Normalize(vmin=0, vmax=100)
        cmap_normal = plt.cm.RdYlGn_r

        cores_linhas = pd.Series(
            [
                COR_SOBRECARGA if v > 100
                else mcolors.to_hex(cmap_normal(norm_0_100(v)))
                for v in carregamento_pct_mapa
            ],
            index=carregamento_pct_mapa.index,
        )
        espessuras_linhas = pd.Series(
            [
                ESPESSURA_SOBRECARGA if v > 100 else ESPESSURA_NORMAL
                for v in carregamento_pct_mapa
            ],
            index=carregamento_pct_mapa.index,
        )

        fig_mapa, ax_mapa = plt.subplots(figsize=(9, 13))
        n.plot(
            ax=ax_mapa,
            geomap=False,             # sem cartopy - usa so as coordenadas x/y locais (ja definidas nos barramentos)
            bus_sizes=eb_geracao_visual,  # indice duplo -> graficos circulares por tecnologia
            line_widths=espessuras_linhas,  # normal para <=100%, mais grossa para >100% (sobrecarga)
            line_colors=cores_linhas,  # cores ja resolvidas explicitamente (gradiente 0-100% + magenta >100%)
            title=f"Producao por tecnologia e carregamento das linhas - {TIMESTAMP_CENARIO.strftime('%d/%m/%Y %H:%M')} (OPF)",
        )
        # Sem geomap (sem projecao cartografica), o matplotlib nao sabe que
        # x (longitude) e y (latitude) devem ter a mesma escala visual -
        # sem isto, o mapa fica esticado e a forma de Portugal irreconhecivel.
        ax_mapa.set_aspect("equal")
        # cmap com "cap" de cor propria para valores acima do vmax (100%) -
        # usa a funcionalidade nativa "extend" do colorbar do matplotlib,
        # que desenha um pequeno bloco/seta na cor indicada mesmo no topo
        # da barra de cor, ligado visualmente a escala - assim fica
        # imediatamente claro que o magenta e uma CONTINUACAO da mesma
        # escala (valores >100%), nao so uma legenda separada e desligada.
        cmap_com_limite = plt.cm.RdYlGn_r.copy()
        cmap_com_limite.set_over(COR_SOBRECARGA)

        sm = plt.cm.ScalarMappable(
            cmap=cmap_com_limite,
            norm=plt.Normalize(vmin=0, vmax=100),
        )
        sm.set_array([])
        plt.colorbar(sm, ax=ax_mapa, extend="max",
                     label="Carregamento (% s_nom)", shrink=0.7)

        # -- Legendas nativas do PyPSA (pypsa.plot) --------------------
        # add_legend_patches: cor de cada tecnologia (fatias dos circulos)
        # (a legenda de espessura de linha foi removida - so a cor
        # representa o carregamento agora, ver colorbar acima)
        try:
            from pypsa.plot import add_legend_patches

            carriers_presentes = eb_geracao.index.get_level_values("carrier").unique()
            carriers_presentes_lista = list(carriers_presentes)
            cores_legenda = [n.carriers.at[c, "color"] for c in carriers_presentes]
            # Acrescenta a cor de sobrecarga como mais uma entrada da legenda,
            # para ficar explicito o que o magenta significa
            if (carregamento_pct_mapa > 100).any():
                carriers_presentes_lista = carriers_presentes_lista + [">100% (sobrecarga)"]
                cores_legenda = cores_legenda + [COR_SOBRECARGA]

            add_legend_patches(
                ax_mapa,
                colors=cores_legenda,
                labels=carriers_presentes_lista,
                legend_kw={"loc": "lower center", "bbox_to_anchor": (0.5, -0.12),
                           "ncol": len(carriers_presentes_lista), "frameon": False},
            )
        except Exception as e_legenda:
            print(f"AVISO: legendas nativas nao adicionadas ({e_legenda}) - "
                  f"o mapa continua valido, so sem legenda explicita.")

        plt.tight_layout()
        f_mapa_congestionamento = RESULTADOS + f"mapa_congestionamento_OPF_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.png"
        plt.savefig(f_mapa_congestionamento, dpi=300, bbox_inches="tight")
        plt.close(fig_mapa)
        print(f"Mapa de congestionamento (n.plot) guardado em: {f_mapa_congestionamento}")
    except Exception as e:
        print(f"AVISO: nao foi possivel gerar o mapa nativo do PyPSA ({e}). "
              f"A assinatura de n.plot() varia entre versoes do PyPSA. "
              f"O resto do script nao e afetado.")

    # -- 13.1.1 Mapa interativo (n.explore) -------------------------------
    # Equivalente interativo do n.plot() (baseado em pydeck) - permite
    # passar o rato sobre cada barramento/linha e ver os seus dados
    # diretamente no navegador. Exportado como ficheiro HTML autonomo
    # (nao precisa de servidor nem de internet para o abrir depois - so
    # o navegador). Util para exploracao durante o desenvolvimento ou
    # complementando a figura estatica gerada na Seccao 6.
    #
    # Dados extra no popup (tooltip): por omissao, o n.explore() so
    # mostra a cor/espessura, sem o VALOR - por isso adiciona-se
    # explicitamente o carregamento (%) como atributo real de cada
    # linha, e a producao por tecnologia (MW) como atributo de cada
    # barramento, via line_columns/bus_columns (funcionalidade nativa do
    # PyPSA para isto - ver User Guide, Maps (Interactive)).
    # NOTA: o n.explore() nao desenha graficos circulares (pie charts)
    # dentro do popup como o n.plot() desenha no mapa - por isso a
    # "fatia" de cada tecnologia aparece aqui como VALOR EM MW (texto),
    # nao como um desenho, mesma informacao mas noutro formato.
    try:
        # Carregamento como atributo real da linha (para aparecer no popup)
        n.lines["carregamento_pct"] = carregamento_pct_mapa.round(1)

        # Producao por tecnologia (MW) como atributo de cada barramento
        producao_por_bus_tecnologia = (
            eb_geracao.unstack(level="carrier").round(1).fillna(0.0)
        )
        colunas_producao = []
        for carrier in producao_por_bus_tecnologia.columns:
            nome_coluna = f"producao_{carrier}_MW"
            n.buses[nome_coluna] = producao_por_bus_tecnologia[carrier].reindex(n.buses.index).fillna(0.0)
            colunas_producao.append(nome_coluna)
        n.buses["producao_total_MW"] = (
            eb_geracao.groupby(level="bus").sum().round(1).reindex(n.buses.index).fillna(0.0)
        )
        colunas_producao.append("producao_total_MW")

        mapa_interativo = n.explore(
            line_width=carregamento_pct_mapa / 10,
            line_color=carregamento_pct_mapa,
            line_columns=["carregamento_pct"],
            bus_columns=colunas_producao,
        )
        f_mapa_interativo = RESULTADOS + f"mapa_interativo_OPF_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.html"
        mapa_interativo.to_html(f_mapa_interativo)
        print(f"Mapa interativo (n.explore) guardado em: {f_mapa_interativo}")
    except Exception as e:
        print(f"AVISO: nao foi possivel gerar o mapa interativo n.explore() "
              f"({e}) - requer o pacote 'pydeck' instalado "
              f"(pip install pydeck / conda install -c conda-forge pydeck). "
              f"O mapa estatico (n.plot) nao e afetado por este erro.")

    # -- 13.2 Estatisticas nativas (n.statistics) ------------------------
    try:
        print("\nBalanco energetico por tecnologia (n.statistics.energy_balance):")
        balanco_energetico = n.statistics.energy_balance()
        print(balanco_energetico)

        fig_stats, ax_stats, _ = n.statistics.energy_balance.plot.bar()
        fig_stats.suptitle(f"Balanco energetico - {CENARIO_ATIVO} (OPF)")
        f_balanco = RESULTADOS + f"balanco_energetico_OPF_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.png"
        fig_stats.savefig(f_balanco, dpi=300, bbox_inches="tight")
        plt.close(fig_stats)
        print(f"Grafico do balanco energetico (n.statistics) guardado em: {f_balanco}")
    except Exception as e:
        print(f"AVISO: nao foi possivel gerar as estatisticas nativas do "
              f"PyPSA ({e}). O modulo n.statistics varia entre versoes do "
              f"PyPSA. O resto do script nao e afetado.")
else:
    print("\n(Visualizacao nativa do PyPSA saltada - o OPF nao correu ou "
          "nao convergiu nesta execucao)")
