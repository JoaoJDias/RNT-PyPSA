"""
Rede de Transporte de Portugal Continental (RNT) - PyPSA
==========================================================
DESPACHO IMPOSTO (SIMULACAO REALISTA) + REDESPACHO + POWER FLOW AC

A construcao da rede (barramentos, linhas, transformadores, cargas,
geracao, importacao) esta agora no modulo partilhado rede_base.py -
ver esse ficheiro para os detalhes dessa parte. Este script trata so
do que e especifico dele: desenho do mapa geografico, despacho
imposto (valores reais), redespacho de seguranca e Power Flow AC.
"""

import os
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from rede_base import construir_rede, resolver_pf_respeitando_capacidade

# <<< Data/hora exata do cenario a simular - funciona para qualquer
# instante de 2024 presente no registo da REN >>>
TIMESTAMP_CENARIO_ALVO =  "2024-01-08 19:45:00"

# Cenarios de referencia (nao usados pelo codigo - alterar a linha acima
# para simular outra data):
#   "2024-01-08 19:45:00"  # Maximo Inverno
#   "2024-05-12 06:30:00"  # Minimo Absoluto
#   "2024-04-25 15:30:00"  # Maxima Injecao Renovavel
#   "2024-07-24 19:45:00"  # Maximo Verao

# ===========================================================================
# 1. OPCOES DE SIMULACAO - configurar aqui antes de correr o script
# ===========================================================================
# CORRER_ATLITE: neste script, o atlite NAO tem qualquer papel no despacho
# IMPOSTO inicial (esse vem sempre de valores reais, sem depender de
# limites de capacidade renovavel). O seu unico papel aqui e servir de
# LIMITE DE SEGURANCA ao redespacho heuristico (Seccao 4): ao tentar
# aumentar geracao eolica/solar num gerador mais distante para aliviar uma
# sobrecarga, o algoritmo usa p_max_pu (calculado aqui) para nunca
# ultrapassar o que a meteorologia real desse instante permite - evita
# despachar mais eolica/solar do que fisicamente possivel. Como o
# redespacho nunca chegou a ser necessario nos cenarios ja testados, este
# limite nunca foi de facto exercido na pratica, mas permanece ativo por
# seguranca caso um cenario futuro o exija.
CORRER_ATLITE = True

# CORRER_PF: ativa o despacho imposto (Excel) + Power Flow AC (Seccao 4).
CORRER_PF = True

# DISTRIBUIR_SLACK: reparte o desequilibrio entre producao imposta e
# carga+perdas por TODOS os geradores sincronos, proporcionalmente ao seu
# despacho - em vez de o concentrar inteiramente no unico gerador Slack
# (Central_Hidroeletrica_Gouvaes_HYD). Adotado como metodo principal (ver
# nota completa junto a chamada n.pf()) por ser mais realista: aproxima a
# regulacao primaria de frequencia real, repartida por varias centrais
# sincronas, nao concentrada artificialmente numa so. Eolica e solar sao
# EXCLUIDAS da distribuicao (peso 0) - na realidade nao participam da
# regulacao primaria de frequencia (sem inercia rotativa sincrona), o
# mesmo criterio ja usado para os candidatos a Slack dinamico no
# contingencia_N1.py (CARRIERS_COM_INERCIA). A importacao e excluida
# pela mesma razao, acrescida de uma segunda: os geradores de fronteira
# representam uma troca ja fixada por p_min_pu = p_max_pu = 1 (Seccao 9.1
# do rede_base.py), nao uma central nacional disponivel para compensar
# desequilibrios. Sem esta exclusao, o Slack distribuido atribui-lhes
# parte das perdas, empurra-os acima do proprio p_nom, e so a verificacao
# de capacidade os traz de volta ao valor real, ao custo de um trânsito
# de potencias adicional por execucao.
DISTRIBUIR_SLACK = True
CARRIERS_EXCLUIDOS_DO_SLACK = ["wind", "solar", "import"]

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

 
# ===========================================================================
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
# 3. FATOR DE CAPACIDADE RENOVAVEL VIA ATLITE (ERA5) - OPCIONAL
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


# ===========================================================================
# NOTA METODOLOGICA: porque nao se usa OPF (n.optimize()) para o despacho
# ===========================================================================
# Foi inicialmente tentado um despacho por Otimizacao Linear (LOPF, via
# n.optimize()), que decide o despacho economico "otimo" dado os custos
# marginais assumidos por tecnologia (ver topologia_OPF.py).
# No entanto, para
# o cenario de Maximo de Inverno esse problema revelou-se INFEASIBLE:
# mesmo havendo capacidade instalada total suficiente para cobrir a carga,
# a rede nao tinha capacidade de transporte (s_nom) suficiente para escoar
# o despacho que o solver escolheria livremente - um congestionamento real
# nalgumas linhas da RNT, confirmado ao relaxar temporariamente os limites
# das linhas (o problema passou a ter solucao otima).
#
# Em vez de adicionar mecanismos de corte de carga (load shedding) para
# contornar essa infeasibilidade, optou-se por uma abordagem mais robusta
# e mais fiel ao objetivo de validacao do modelo: IMPOR o despacho REAL
# (registado pela REN no Excel, por tecnologia) a cada gerador, distribuido
# proporcionalmente pela capacidade instalada de cada um, e correr apenas o
# Power Flow nao linear (AC) sobre esse despacho conhecido. Isto elimina a
# infeasibilidade por construcao (o despacho ja nao e uma decisao do
# solver) e permite validar diretamente se a TOPOLOGIA e os PARAMETROS da
# rede (linhas, transformadores, s_nom sazonais) sao capazes de escoar um
# despacho que sabemos ter acontecido na realidade.
#
# A abordagem alternativa por OPF (com atlite, compensacao iterativa de
# perdas e fallback Gurobi para diagnostico de infeasibility) esta mantida
# em separado, no ficheiro topologia_OPF.py.


# ===========================================================================
# 4. DESPACHO IMPOSTO + TRANSITO DE POTENCIAS NAO LINEAR (AC)
# ===========================================================================
# Ver CORRER_PF e DISTRIBUIR_SLACK na seccao de OPCOES DE SIMULACAO, no
# topo do ficheiro.
if CORRER_PF:
    print("\n" + "=" * 60)
    print("A APLICAR DESPACHO REAL (EXCEL) E EXECUTAR POWER FLOW AC")
    print("=" * 60)

    # -- 12.1 Obter a producao real do Excel para a hora do cenario -----
    fossil_real = (
        _excel.loc[TIMESTAMP_CENARIO, "Gás Natural - Ciclo Combinado"]
        + _excel.loc[TIMESTAMP_CENARIO, "Gás natural - Cogeração"]
        + _excel.loc[TIMESTAMP_CENARIO, "Carvão"]
        + _excel.loc[TIMESTAMP_CENARIO, "Outra Térmica"]
    )
    
    producao_real = {
        "hydro": _excel.loc[TIMESTAMP_CENARIO, "Hídrica"],
        "wind": _excel.loc[TIMESTAMP_CENARIO, "Eólica"],
        "solar": _excel.loc[TIMESTAMP_CENARIO, "Solar"],
        "biomass": _excel.loc[TIMESTAMP_CENARIO, "Biomassa"],
        "fossil": fossil_real
    }

    # -- 12.2 Distribuir a producao pelos geradores no PyPSA ------------
    # O script pega no total de ex: Eolica e distribui por todos os parques
    # consoante a capacidade instalada (p_nom) de cada um.
    for carrier, valor_total_real in producao_real.items():
        gens = n.generators[n.generators.carrier == carrier]
        if not gens.empty and gens.p_nom.sum() > 0:
            pesos = gens.p_nom / gens.p_nom.sum()
            n.generators.loc[gens.index, "p_set"] = pesos * valor_total_real

    # Garantir que a Importacao tambem assume o valor (p_nom ja foi dividido na Seccao 2.1 do rede_base.py)
    importadores = n.generators[n.generators.carrier == "import"].index
    if not importadores.empty:
        n.generators.loc[importadores, "p_set"] = n.generators.loc[importadores, "p_nom"]

    print("\nDespacho forcado (real) aplicado ao modelo (MW):")
    print(n.generators.groupby("carrier")["p_set"].sum().round(1))

    # -- 12.3 Redespacho de seguranca + Power Flow Nao-Linear (AC) ------
    # O despacho imposto (12.1-12.2) distribui a producao real de cada
    # tecnologia PROPORCIONALMENTE pela capacidade instalada de cada
    # gerador - uma simplificacao que ignora a localizacao geografica na
    # rede. Isto pode gerar fluxos fisicamente implausiveis nalgumas
    # linhas (confirmado: a Falagueira-Estremoz aparecia a >200% de
    # carregamento mesmo com r/x/s_nom corretos e batendo certo com o
    # Anexo B da REN - ver nota do email/reuniao com o orientador).
    #
    # A REN documenta explicitamente na Caracterizacao da RNT que gere
    # este tipo de situacao atraves de "restricoes a geracao" - ou seja,
    # reduz deliberadamente a producao de centrais especificas para
    # aliviar corredores congestionados, compensando com mais producao
    # da MESMA tecnologia noutros pontos da rede. O bloco abaixo imita
    # esse comportamento de forma simplificada (heuristica), mantendo o
    # total nacional por tecnologia EXATAMENTE igual ao valor do Excel -
    # so a distribuicao espacial dentro de cada tecnologia e ajustada.
    #
    # Metodo (redespacho heuristico baseado em distancia na rede):
    #   1. Corre o Power Flow AC e identifica a linha mais sobrecarregada
    #      (> LIMIAR_VIOLACAO_PCT do s_nom).
    #   2. Identifica de que lado da linha vem o fluxo em excesso (bus
    #      "emissor").
    #   3. Para cada tecnologia com geradores fisicamente proximos desse
    #      bus emissor (dentro de RAIO_ZONA_ENVIO_HOPS "saltos" na rede),
    #      reduz-lhes um pequeno passo de producao (PASSO_REDESPACHO_MW)
    #      e atribui a mesma quantidade a geradores da MESMA tecnologia
    #      mais distantes (com folga disponivel ate ao seu p_nom).
    #   4. Repete ate nao restarem violacoes ou atingir o numero maximo
    #      de iteracoes.
    #
    # NOTA METODOLOGICA: este e um redespacho
    # HEURISTICO, nao um redespacho otimo (que exigiria uma otimizacao
    # completa tipo OPF com restricoes de seguranca - ver
    # topologia_OPF.py para essa alternativa). Serve para obter um
    # despacho fisicamente viavel e proximo do real, nao para encontrar
    # a solucao economica ou tecnicamente "otima".
    LIMIAR_VIOLACAO_PCT = 100.0
    RAIO_ZONA_ENVIO_HOPS = 2
    PASSO_REDESPACHO_MW = 20.0
    MAX_ITER_REDESPACHO = 150

    def construir_grafo_rede(n):
        G = nx.Graph()
        G.add_nodes_from(n.buses.index)
        G.add_edges_from(zip(n.lines.bus0, n.lines.bus1))
        G.add_edges_from(zip(n.transformers.bus0, n.transformers.bus1))
        return G

    def aplicar_passo_redespacho(n, G, elemento_nome, tipo_elemento="Line"):
        """Reduz um pequeno passo de producao nos geradores de cada
        tecnologia fisicamente proximos do lado emissor do elemento
        sobrecarregado (linha OU transformador), compensando em
        geradores da MESMA tecnologia mais distantes com folga
        disponivel. Devolve True se conseguiu ajustar alguma coisa."""
        if tipo_elemento == "Transformer":
            df_componente = n.transformers
            fluxo_p0 = n.transformers_t.p0.loc[n.snapshots[0], elemento_nome]
        else:
            df_componente = n.lines
            fluxo_p0 = n.lines_t.p0.loc[n.snapshots[0], elemento_nome]

        bus0 = df_componente.at[elemento_nome, "bus0"]
        bus1 = df_componente.at[elemento_nome, "bus1"]
        bus_emissor = bus0 if fluxo_p0 > 0 else bus1

        try:
            dist_emissor = nx.single_source_shortest_path_length(G, bus_emissor)
        except Exception:
            return False

        ajustou_algo = False
        for carrier in n.generators.carrier.unique():
            if carrier == "import":
                continue  # importacao fica fixa (secao 6.1), nao e redespachavel

            gens_carrier = n.generators[n.generators.carrier == carrier]
            if gens_carrier.empty:
                continue

            proximos = [
                g for g in gens_carrier.index
                if dist_emissor.get(n.generators.at[g, "bus"], 999) <= RAIO_ZONA_ENVIO_HOPS
                and n.generators.at[g, "p_set"] > 0.1
            ]
            if not proximos:
                continue

            distantes = sorted(
                gens_carrier.index,
                key=lambda g: -dist_emissor.get(n.generators.at[g, "bus"], 0),
            )
            distantes = [
                g for g in distantes
                if (n.generators.at[g, "p_nom"] * n.generators.at[g, "p_max_pu"]
                    - n.generators.at[g, "p_set"]) > 0.1
            ]
            if not distantes:
                continue

            reduzido = 0.0
            for g in proximos:
                corte = min(PASSO_REDESPACHO_MW - reduzido, n.generators.at[g, "p_set"])
                n.generators.at[g, "p_set"] -= corte
                reduzido += corte
                if reduzido >= PASSO_REDESPACHO_MW:
                    break

            restante = reduzido
            for g in distantes:
                p_max = n.generators.at[g, "p_nom"] * n.generators.at[g, "p_max_pu"]
                folga = p_max - n.generators.at[g, "p_set"]
                incremento = min(folga, restante)
                n.generators.at[g, "p_set"] += incremento
                restante -= incremento
                if restante <= 1e-6:
                    break

            if reduzido > 0:
                ajustou_algo = True

        return ajustou_algo

    print("\n" + "-" * 40)
    print("A iniciar Power Flow AC + redespacho de seguranca...")

    G_rede = construir_grafo_rede(n)
    redespacho_total_mw = 0.0
    convergiu = False

    # Pesos personalizados para a distribuicao do Slack: proporcional ao
    # despacho (p_set), mas com eolica e solar excluidas (peso 0) - ver
    # nota completa acima (DISTRIBUIR_SLACK). A organizacao por sub-rede,
    # exigida pelo PyPSA, e feita internamente por
    # resolver_pf_respeitando_capacidade() (rede_base.py).
    pesos_slack_todos = n.generators["p_set"].copy()
    pesos_slack_todos[n.generators["carrier"].isin(CARRIERS_EXCLUIDOS_DO_SLACK)] = 0.0

    for iteracao in range(1, MAX_ITER_REDESPACHO + 1):
        # resolver_pf_respeitando_capacidade() fixa em p_nom o p_set de
        # qualquer gerador que o Slack distribuido empurre acima da sua
        # capacidade. Essa alteracao e necessaria DURANTE a resolucao,
        # mas nao deve sobreviver-lhe: sem esta copia, o p_set deixaria
        # de representar o despacho imposto (mais o redespacho aplicado)
        # e o total nacional da tecnologia em causa apareceria acima do
        # valor do Excel no relatorio final. O mesmo cuidado ja e tido
        # entre testes no contingencia_N1.py.
        p_set_antes_do_pf = n.generators["p_set"].copy()
        try:
            # NOTA METODOLOGICA: por omissao
            # (distribute_slack=False), o PyPSA atribui TODO o
            # desequilibrio entre producao imposta e carga+perdas ao
            # unico gerador Slack, que passa assim a absorver sozinho
            # qualquer desvio do balanco energetico. O
            # PyPSA suporta nativamente distribute_slack=True, que
            # reparte esse desequilibrio por TODOS os geradores,
            # proporcionalmente ao seu despacho - uma alternativa mais
            # realista (aproxima a regulacao primaria de frequencia
            # real, partilhada entre varias centrais, nao concentrada
            # numa so) a comparar com o resultado por omissao. Os pesos
            # personalizados (PESOS_SLACK) excluem eolica/solar da
            # distribuicao, por nao participarem da regulacao primaria
            # de frequencia real (sem inercia rotativa sincrona).
            convergiu, capados = resolver_pf_respeitando_capacidade(
                n, pesos_slack_todos, DISTRIBUIR_SLACK, verbose=(iteracao == 1)
            )
        except Exception as e:
            print(f"\nERRO FATAL NO POWER FLOW (iteracao {iteracao}): {e}")
            break
        finally:
            # Reposto sempre, mesmo em caso de erro, para o estado da
            # rede ficar coerente com o despacho imposto. Os resultados
            # do trânsito de potências (n.generators_t.p, n.lines_t.p0,
            # n.buses_t.v_mag_pu) ja estao calculados nesta altura e nao
            # sao afetados por esta reposicao.
            n.generators["p_set"] = p_set_antes_do_pf

        if not convergiu:
            print(f"\nPower flow nao convergiu na iteracao {iteracao} - a parar redespacho.")
            break

        # Carregamento de linhas E transformadores: um transformador
        # sobrecarrega tal como uma linha, e a analise N-1 ja os verifica,
        # pelo que o redespacho de seguranca tambem os deve considerar.
        carreg_linhas = (n.lines_t.p0.abs().iloc[0] / n.lines.s_nom * 100)
        carreg_trafos = (n.transformers_t.p0.abs().iloc[0] / n.transformers.s_nom * 100)
        carregamento = pd.concat([carreg_linhas, carreg_trafos])
        tipo_por_elemento = {
            **{nome: "Line" for nome in carreg_linhas.index},
            **{nome: "Transformer" for nome in carreg_trafos.index},
        }
        violadas = carregamento[carregamento > LIMIAR_VIOLACAO_PCT].sort_values(ascending=False)

        if violadas.empty:
            if iteracao == 1:
                print("\nNenhum elemento violado - despacho imposto ja e viavel, sem "
                      "necessidade de redespacho.")
            else:
                print(f"\nTodas as violacoes eliminadas apos {iteracao - 1} "
                      f"iteracao(oes) de redespacho.")
            break

        elemento_pior = violadas.index[0]
        tipo_pior = tipo_por_elemento[elemento_pior]
        if iteracao == 1 or iteracao % 5 == 0:
            print(f"  Iteracao {iteracao}: {len(violadas)} elemento(s) violado(s) "
                  f"(pior: {elemento_pior} [{tipo_pior}] a {violadas.iloc[0]:.1f}%)")

        ajustou = aplicar_passo_redespacho(n, G_rede, elemento_pior, tipo_pior)
        if not ajustou:
            print(f"\nAVISO: sem geradores disponiveis (mesma tecnologia, com folga) "
                  f"para redespachar '{elemento_pior}' - a parar com violacao residual.")
            break
        redespacho_total_mw += PASSO_REDESPACHO_MW
    else:
        print(f"\nAVISO: atingido o limite de {MAX_ITER_REDESPACHO} iteracoes de "
              f"redespacho sem eliminar todas as violacoes.")

    print(f"\nRedespacho total aplicado: {redespacho_total_mw:.1f} MW "
          f"(realocado dentro de cada tecnologia - os totais nacionais por "
          f"tecnologia mantem-se iguais aos valores reais do Excel)")

    if convergiu:
        print(f"\nPower flow (estado final) convergiu: {convergiu}")

        print("\nDespacho final por tecnologia (MW) - deve coincidir com o real:")
        print(n.generators.groupby("carrier")["p_set"].sum().round(1))

        print("\nTensoes nos barramentos (p.u.) - resumo:")
        print(n.buses_t.v_mag_pu.T.describe().round(4))

        # Relatorio final sobre os DOIS tipos de elemento, o mesmo
        # universo ja usado na deteccao de violacoes do ciclo de
        # redespacho acima - de outro modo, um transformador entre os
        # mais carregados da rede nunca chegaria a ser reportado.
        print("\nCarregamento de linhas e transformadores (% de s_nom) - top 10:")
        carregamento_final = pd.concat([
            (n.lines_t.p0.abs().iloc[0] / n.lines.s_nom * 100),
            (n.transformers_t.p0.abs().iloc[0] / n.transformers.s_nom * 100),
        ]).sort_values(ascending=False)
        print(carregamento_final.head(10).round(2))

        print(f"\nPerdas totais nas linhas (MW): {(n.lines_t.p0.iloc[0] + n.lines_t.p1.iloc[0]).sum():.2f}")

        # -- 12.4 Guardar a rede com resultados do PF --------------------
        F_RESULTADO_PF = rf"{CACHE}rnt_portugal_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}_pf_resultado.nc"
        n.export_to_netcdf(F_RESULTADO_PF)
        print(f"\nRede com resultados do power flow guardada em {F_RESULTADO_PF}")
    else:
        print("\nNao foi possivel obter um resultado final valido do power flow.")

else:
    print("\n(Bloco de power flow desativado - muda CORRER_PF para True para ativar)")


# ===========================================================================
# 5. VISUALIZACAO NATIVA DO PYPSA (CONGESTIONAMENTO + ESTATISTICAS)
# ===========================================================================
# METODOLOGIA: em vez de depender so do mapa
# desenhado manualmente (Seccao 2, matplotlib puro, sem recorrer a nenhuma
# funcionalidade nativa do PyPSA), esta seccao usa explicitamente as
# ferramentas de visualizacao INCLUIDAS no PyPSA - n.plot() (mapa) e o
# modulo n.statistics (metricas/graficos) - que ja sabem posicionar a rede
# a partir das coordenadas dos barramentos e mapear resultados
# (carregamento, despacho) diretamente em cores/espessuras, sem
# reimplementar essa logica a mao. Complementa, nao substitui, o mapa da
# Seccao 2.
#
# A assinatura de n.plot() (nomes de parametros como line_colors e
# line_cmap) varia entre versoes do PyPSA. O try/except abaixo garante que
# uma eventual incompatibilidade nao interrompe a execucao do script.
if CORRER_PF and convergiu:
    print("\n" + "=" * 60)
    print("VISUALIZACAO NATIVA DO PYPSA")
    print("=" * 60)

    # -- 5.1 Mapa de congestionamento (n.plot) --------------------------
    # Cor E espessura das linhas proporcionais ao carregamento (% de
    # s_nom) - visualiza diretamente os pontos de congestionamento da
    # rede. Os barramentos sao desenhados como GRAFICOS
    # CIRCULARES (pie charts) com a reparticao da producao REAL por
    # tecnologia nesse ponto (n.generators_t.p, nao o p_set imposto - ver
    # nota metodologica da Seccao 4 sobre a diferenca entre os dois),
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
            title=f"Producao por tecnologia e carregamento das linhas - {TIMESTAMP_CENARIO.strftime('%d/%m/%Y %H:%M')}",
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
        f_mapa_congestionamento = RESULTADOS + f"mapa_congestionamento_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.png"
        plt.savefig(f_mapa_congestionamento, dpi=300, bbox_inches="tight")
        plt.close(fig_mapa)
        print(f"Mapa de congestionamento (n.plot) guardado em: {f_mapa_congestionamento}")
    except Exception as e:
        print(f"AVISO: nao foi possivel gerar o mapa nativo do PyPSA ({e}). "
              f"A assinatura de n.plot() varia entre versoes do PyPSA. "
              f"O resto do script nao e afetado.")

    # -- 12.1.1 Mapa interativo (n.explore) -------------------------------
    # Equivalente interativo do n.plot() (baseado em pydeck) - permite
    # passar o rato sobre cada barramento/linha e ver os seus dados
    # diretamente no navegador. Exportado como ficheiro HTML autonomo
    # (nao precisa de servidor nem de internet para o abrir depois - so
    # o navegador). Util para exploracao interativa dos resultados,
    # complementando a figura estatica gerada na Seccao 5.
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
        f_mapa_interativo = RESULTADOS + f"mapa_interativo_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.html"
        mapa_interativo.to_html(f_mapa_interativo)
        print(f"Mapa interativo (n.explore) guardado em: {f_mapa_interativo}")
    except Exception as e:
        print(f"AVISO: nao foi possivel gerar o mapa interativo n.explore() "
              f"({e}) - requer o pacote 'pydeck' instalado "
              f"(pip install pydeck / conda install -c conda-forge pydeck). "
              f"O mapa estatico (n.plot) nao e afetado por este erro.")

    # -- 12.2 Estatisticas nativas (n.statistics) ------------------------
    # Balanco energetico por tecnologia (Carrier), calculado pelo proprio
    # PyPSA (em vez do groupby manual usado nas seccoes anteriores) -
    # metodo mais citavel/reprodutivel, com grafico pronto a usar direto
    # do modulo de estatisticas.
    try:
        print("\nBalanco energetico por tecnologia (n.statistics.energy_balance):")
        balanco_energetico = n.statistics.energy_balance()
        print(balanco_energetico)

        fig_stats, ax_stats, _ = n.statistics.energy_balance.plot.bar()
        fig_stats.suptitle(f"Balanco energetico - {CENARIO_ATIVO} (despacho real)")
        f_balanco = RESULTADOS + f"balanco_energetico_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.png"
        fig_stats.savefig(f_balanco, dpi=300, bbox_inches="tight")
        plt.close(fig_stats)
        print(f"Grafico do balanco energetico (n.statistics) guardado em: {f_balanco}")
    except Exception as e:
        print(f"AVISO: nao foi possivel gerar as estatisticas nativas do "
              f"PyPSA ({e}). O modulo n.statistics varia entre versoes do "
              f"PyPSA. O resto do script nao e afetado.")
else:
    print("\n(Visualizacao nativa do PyPSA saltada - o power flow nao "
          "correu ou nao convergiu nesta execucao)")
