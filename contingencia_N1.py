"""
Rede de Transporte de Portugal Continental (RNT) - PyPSA
==========================================================
ANALISE DE CONTINGENCIA N-1 (LINHAS E TRANSFORMADORES)

A construcao da rede (barramentos, linhas, transformadores, cargas,
geracao, importacao) esta agora no modulo partilhado rede_base.py -
ver esse ficheiro para os detalhes dessa parte. Este script trata so
do que e especifico dele: aplicar o despacho real (caso base) e
correr a analise de contingencia N-1 sobre os elementos da rede
passiveis de contingencia. Dos 385 elementos existentes (347 linhas
+ 38 transformadores), sao testados 338; os restantes 47 sao radiais
e ficam excluidos automaticamente (ver Seccao 3.1).

Cada elemento e removido de facto (n.remove) - se isso isolar uma
zona sem o gerador Slack original, o script atribui dinamicamente o
Slack ao maior gerador sincrono disponivel nessa zona
(hidrica/fossil/biomassa), imitando a regulacao primaria de
frequencia real, antes de correr o Power Flow.
"""

import os
import pandas as pd
import networkx as nx

from rede_base import construir_rede, resolver_pf_respeitando_capacidade

# <<< Define aqui a data/hora exata do cenario a simular - funciona para
# QUALQUER instante de 2024 presente no registo da REN >>>
TIMESTAMP_CENARIO_ALVO = "2024-07-24 19:45:00"  # Maximo Verao

# Cenarios de referencia (nao usados pelo codigo - alterar a linha acima
# para simular outra data):
#   "2024-01-08 19:45:00"  # Maximo Inverno
#   "2024-05-12 06:30:00"  # Minimo Absoluto
#   "2024-04-25 15:30:00"  # Maxima Injecao Renovavel
#   "2024-07-24 19:45:00"  # Maximo Verao

# ===========================================================================
# 1. OPCOES DE SIMULACAO - configurar aqui antes de correr o script
# ===========================================================================
# DISTRIBUIR_SLACK: reparte o desequilibrio entre despacho imposto e
# carga+perdas por todos os geradores sincronos, em vez de o concentrar
# inteiramente no Slack (original OU o reatribuido dinamicamente para uma
# zona isolada). Eolica e solar excluidas (peso 0). NOTA: isto NAO
# substitui a logica de reatribuicao dinamica de Slack ja existente
# (continua a ser necessaria para garantir uma referencia valida por
# sub-rede) - so muda como o desequilibrio de POTENCIA e repartido,
# depois de essa referencia estar garantida. Ver nota completa na Seccao
# 4 do topologia.py, onde foi validado primeiro.
DISTRIBUIR_SLACK = True
# A importacao e excluida pela mesma razao que a eolica e a solar, sem
# inercia rotativa sincrona, acrescida de uma segunda: os geradores de
# fronteira representam uma troca ja fixada por p_min_pu = p_max_pu = 1
# (Seccao 9.1 do rede_base.py), nao uma central nacional disponivel para
# compensar desequilibrios.
CARRIERS_EXCLUIDOS_DO_SLACK = ["wind", "solar", "import"]

# LIMIAR_VIOLACAO_PCT: percentagem da capacidade termica (s_nom) acima da
# qual um elemento e considerado em sobrecarga. Definido aqui, no bloco de
# opcoes, e nao junto ao ciclo N-1 (Seccao 3), porque e usado nos DOIS
# sitios: na validacao do caso base (Seccao 2) e na classificacao de cada
# contingencia (Seccao 4). Ter o valor num unico sitio garante que os dois
# criterios nunca divergem.
LIMIAR_VIOLACAO_PCT = 100.0

# SO_CASO_BASE: termina o script logo apos a validacao do caso base
# (Seccao 2), sem correr o ciclo de contingencias (Seccao 4). Serve para
# reverificar em segundos o carregamento da rede intacta, em vez dos ~10
# minutos da analise N-1 completa, sempre que se muda de cenario ou se
# altera algum parametro do modelo. Nao altera nada do que e calculado:
# a validacao do caso base e exatamente a mesma nos dois modos.
SO_CASO_BASE = False

ctx = construir_rede(TIMESTAMP_CENARIO_ALVO)
n = ctx.n
CAMINHO = ctx.CAMINHO

# Pasta dos resultados gerados por este script (mapas, graficos, tabelas),
# criada automaticamente na primeira execucao.
RESULTADOS = os.path.join(CAMINHO, "resultados") + os.sep
os.makedirs(RESULTADOS, exist_ok=True)

TIMESTAMP_CENARIO = ctx.TIMESTAMP_CENARIO
_excel = ctx._excel
barramentos = ctx.barramentos
linhas = ctx.linhas
trafos = ctx.trafos
geracao = ctx.geracao


def calcular_pesos_slack(n):
    """Constroi os pesos do slack distribuido (proporcional ao p_set,
    eolica/solar excluidas). A organizacao por sub-rede, exigida pelo
    PyPSA, e feita internamente por resolver_pf_respeitando_capacidade()
    (rede_base.py) - recalculado sempre que a topologia muda (cada
    teste N-1 tem uma configuracao de sub-redes potencialmente
    diferente), por isso esta funcao e chamada de novo a cada teste."""
    pesos_todos = n.generators["p_set"].copy()
    pesos_todos[n.generators["carrier"].isin(CARRIERS_EXCLUIDOS_DO_SLACK)] = 0.0
    return pesos_todos


# ===========================================================================
# 2. DESPACHO IMPOSTO - base para a analise N-1
# ===========================================================================
# Mesma logica do topologia.py (Seccao 4): distribui a producao
# real de cada tecnologia (Excel/REN Data Hub) proporcionalmente pela
# capacidade instalada de cada gerador. E' o "caso base" (sem nenhuma
# contingencia) sobre o qual a analise N-1 e feita - pratica standard em
# estudos de seguranca de redes.
print("\n" + "=" * 60)
print("A APLICAR DESPACHO REAL (EXCEL) - CASO BASE PARA ANALISE N-1")
print("=" * 60)

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
    "fossil": fossil_real,
}

for carrier, valor_total_real in producao_real.items():
    gens = n.generators[n.generators.carrier == carrier]
    if not gens.empty and gens.p_nom.sum() > 0:
        pesos = gens.p_nom / gens.p_nom.sum()
        n.generators.loc[gens.index, "p_set"] = pesos * valor_total_real

importadores = n.generators[n.generators.carrier == "import"].index
if not importadores.empty:
    n.generators.loc[importadores, "p_set"] = n.generators.loc[importadores, "p_nom"]

print("\nDespacho forcado (real) aplicado ao modelo (MW):")
print(n.generators.groupby("carrier")["p_set"].sum().round(1))

# O caso base (sem nenhuma contingencia) e validado antes da analise
# N-1: testar contingencias sobre um caso base ja inviavel nao produz
# resultados interpretaveis.
print("\nA validar o caso base (sem contingencias)...")
convergiu_base, capados_base = resolver_pf_respeitando_capacidade(
    n, calcular_pesos_slack(n), DISTRIBUIR_SLACK, verbose=True
)
if not convergiu_base:
    raise SystemExit("O caso base nao converge - corrigir antes de avancar "
                      "para a analise N-1.")
# O carregamento do caso base e avaliado sobre os DOIS tipos de elemento,
# linhas e transformadores, exatamente com o mesmo criterio usado depois
# na classificacao de cada contingencia (Seccao 4) - de outro modo, uma
# sobrecarga de transformador ja presente na rede intacta passaria
# despercebida aqui e seria atribuida, mais tarde, a contingencia que
# calhasse a ser testada.
carregamento_base_linhas = (n.lines_t.p0.abs().iloc[0] / n.lines.s_nom * 100)
carregamento_base_trafos = (
    n.transformers_t.p0.abs().iloc[0]
    / n.transformers.s_nom.replace(0, float("nan")) * 100
)
carregamento_base = pd.concat([carregamento_base_linhas, carregamento_base_trafos])
violacoes_base = carregamento_base[carregamento_base > LIMIAR_VIOLACAO_PCT]
if not violacoes_base.empty:
    print(f"AVISO: o caso base ja tem {len(violacoes_base)} elemento(s) "
          f"acima de {LIMIAR_VIOLACAO_PCT:.0f}% antes de qualquer "
          f"contingencia:")
    print(violacoes_base.sort_values(ascending=False).round(2))
else:
    print("Caso base validado: convergiu, sem violacoes de carregamento "
          "em linhas nem em transformadores.")
    print(f"  Linha mais carregada:         "
          f"{carregamento_base_linhas.idxmax()} a "
          f"{carregamento_base_linhas.max():.2f}%")
    print(f"  Transformador mais carregado: "
          f"{carregamento_base_trafos.idxmax()} a "
          f"{carregamento_base_trafos.max():.2f}%")

if SO_CASO_BASE:
    print("\n(SO_CASO_BASE ativo: a terminar aqui, sem correr o ciclo N-1. "
          "Muda esta opcao para False no topo do ficheiro para a analise "
          "completa.)")
    raise SystemExit


# ===========================================================================
# 3. CONFIGURACAO DA ANALISE N-1 (LINHAS E TRANSFORMADORES)
# ===========================================================================
# METODOLOGIA: criterio de seguranca N-1, standard
# na industria e adotado pela ENTSO-E/REN - a rede deve manter-se dentro
# de limites operacionais seguros apos a perda de QUALQUER elemento
# individual (linha OU transformador). Cada elemento e retirado UM DE
# CADA VEZ (nunca mais que um em simultaneo), o Power Flow AC e
# recalculado, os resultados sao registados, e o elemento e REPOSTO
# antes do teste seguinte - os testes sao independentes entre si (nao
# cumulativos).
#
# O elemento e REMOVIDO de facto da rede (n.remove), nao so com a
# impedancia inflada - isto e necessario para que o PyPSA reconheca
# corretamente a divisao em duas sub-redes (n.determine_network_topology)
# quando a perda do elemento isola uma zona. So assim e possivel
# atribuir dinamicamente um novo gerador Slack a essa zona, se ela ficar
# sem o Slack original (ver SLACK DINAMICO abaixo).
#
# SLACK DINAMICO: no sistema eletrico real, se a central que fornece a
# referencia de frequencia perder a ligacao a uma zona da rede, OUTRA
# central sincrona de grande porte dessa zona assume esse papel
# automaticamente (regulacao primaria de frequencia). O modelo, por
# omissao, so tem 1 gerador Slack fixo em toda a rede - por isso, sempre
# que uma contingencia isola uma zona sem o Slack original, o script
# atribui-o dinamicamente ao MAIOR gerador sincrono (por capacidade
# instalada, entre as tecnologias com inercia rotativa real: hidrica,
# fossil, biomassa - NAO eolica/solar/importacao, que nao tem massa
# girante sincrona) disponivel nessa zona, antes de correr o Power Flow.
# So se a zona nao tiver NENHUM gerador sincrono disponivel e que fica
# classificada como perda de alimentacao total.
#
# Cada teste verifica quatro tipos de resultado possiveis, distintos:
#   1. ILHA / PERDA DE ALIMENTACAO TOTAL - a zona isolada nao tem
#      NENHUM gerador sincrono disponivel para assumir o Slack.
#   2. NAO CONVERGE - o Power Flow AC nao encontra solucao (mesmo com o
#      Slack dinamico atribuido).
#   3. SOBRECARGA - a rede continua ligada (ou o Slack foi reatribuido
#      com sucesso) e o PF converge, mas alguma linha ou transformador
#      fica acima de 100% da capacidade termica.
#   4. OK - sem violacoes (pode ou nao ter havido reatribuicao de Slack).
CARRIERS_COM_INERCIA = ["hydro", "fossil", "biomass"]
# LIMIAR_VIOLACAO_PCT esta definido no bloco de OPCOES DE SIMULACAO, no
# topo do ficheiro, por ser partilhado com a validacao do caso base
# (Seccao 2) - ver a nota junto a sua definicao.


# Guarda o estado ORIGINAL do control de TODOS os geradores, uma unica
# vez, antes do ciclo comecar. No fim de CADA iteracao, repomos esta
# copia completa (nao so os geradores que julgamos ter mudado) - isto
# elimina por completo qualquer risco de "fuga" de Slack dinamico entre
# testes consecutivos (ex: um Slack atribuido numa iteracao a ficar por
# engano ativo na iteracao seguinte, com 2 Slacks na mesma sub-rede,
# o que impede o Power Flow de convergir).
CONTROLS_ORIGINAIS = n.generators["control"].copy()
# Guardado pela mesma razao que CONTROLS_ORIGINAIS: resolver_pf_respeitando_
# capacidade() (rede_base.py) pode fixar o p_set de um gerador que exceda a
# sua capacidade durante um teste. Sem repor este valor a cada iteracao,
# essa alteracao persistiria para os testes seguintes, contaminando-os.
P_SET_ORIGINAL = n.generators["p_set"].copy()

# ---------------------------------------------------------------------------
# 3.1 Filtrar elementos radiais (excluidos do teste N-1)
# ---------------------------------------------------------------------------
# METODOLOGIA: um elemento e "radial" quando e a
# UNICA ligacao de um barramento ao resto da rede - nesse caso, a sua
# remocao isola SEMPRE esse barramento, por definicao topologica, sem
# ser preciso correr o Power Flow para o saber (o resultado e trivial e
# conhecido a priori). Na pratica de engenharia de redes, o criterio
# N-1 aplica-se ao "backbone" malhado da rede de transporte - ramais
# radiais para uma unica carga, central ou ponto de interligacao
# internacional ficam tipicamente FORA do ambito da analise N-1, porque
# a sua vulnerabilidade e conhecida e aceite a priori, nao uma
# descoberta da analise.
#
# Deteta-se automaticamente: constroi-se o grafo completo da rede
# (todas as linhas + todos os transformadores), calcula-se o grau de
# cada barramento (numero de ligacoes), e qualquer barramento com grau
# 1 tem, por definicao, uma UNICA linha/transformador a liga-lo - esse
# elemento e classificado como radial e excluido da lista de teste.
#
# IMPORTANTE: usa-se MultiGraph (nao Graph simples) porque alguns pares
# de barramentos tem LINHAS PARALELAS entre si (ex: dois circuitos
# entre a mesma subestacao) - um grafo simples colapsaria essas duas
# linhas numa unica aresta, fazendo esse barramento parecer ter grau 1
# (radial) quando na realidade tem 2 ligacoes fisicas independentes
# (redundancia real, nao radial).
G_completo = nx.MultiGraph()
G_completo.add_nodes_from(n.buses.index)
G_completo.add_edges_from(zip(n.lines.bus0, n.lines.bus1))
G_completo.add_edges_from(zip(n.transformers.bus0, n.transformers.bus1))

graus = dict(G_completo.degree())
barramentos_terminais = [bus for bus, grau in graus.items() if grau == 1]

elementos_radiais = set()
for bus in barramentos_terminais:
    vizinhos = list(G_completo.neighbors(bus))
    if not vizinhos:
        continue
    vizinho = vizinhos[0]
    # identifica se a ligacao e uma linha ou um transformador
    linha_match = n.lines[
        ((n.lines.bus0 == bus) & (n.lines.bus1 == vizinho))
        | ((n.lines.bus0 == vizinho) & (n.lines.bus1 == bus))
    ]
    if not linha_match.empty:
        elementos_radiais.add(("Line", linha_match.index[0]))
        continue
    trafo_match = n.transformers[
        ((n.transformers.bus0 == bus) & (n.transformers.bus1 == vizinho))
        | ((n.transformers.bus0 == vizinho) & (n.transformers.bus1 == bus))
    ]
    if not trafo_match.empty:
        elementos_radiais.add(("Transformer", trafo_match.index[0]))

print(f"\n{len(barramentos_terminais)} barramento(s) terminal(is) (grau 1) "
      f"detetado(s) -> {len(elementos_radiais)} elemento(s) radial(is) "
      f"excluido(s) do teste N-1 (vulnerabilidade trivial/conhecida a priori):")
for tipo, nome in sorted(elementos_radiais):
    print(f"  - [{tipo}] {nome}")

F_RADIAIS = RESULTADOS + f"elementos_radiais_excluidos_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.csv"
pd.DataFrame(sorted(elementos_radiais), columns=["tipo", "elemento"]).to_csv(
    F_RADIAIS, index=False
)
print(f"Lista de elementos radiais excluidos guardada em: {F_RADIAIS}")

# Lista combinada de TODOS os elementos a testar (transformadores +
# linhas), EXCLUINDO os radiais identificados acima.
# ===========================================================================
# 4. EXECUCAO DO CICLO N-1
# ===========================================================================
elementos_a_testar = [
    ("Transformer", nome) for nome in n.transformers.index
    if ("Transformer", nome) not in elementos_radiais
] + [
    ("Line", nome) for nome in n.lines.index
    if ("Line", nome) not in elementos_radiais
]
TOTAL_ELEMENTOS = len(elementos_a_testar)

resultados_n1 = []

print("\n" + "=" * 60)
print(f"ANALISE DE CONTINGENCIA N-1 - {TOTAL_ELEMENTOS} ELEMENTOS "
      f"(apos excluir {len(elementos_radiais)} radiais)")
print("=" * 60)


def obter_atributos(tipo, nome):
    """Guarda os atributos originais de uma linha ou transformador,
    para poder repo-lo depois de o remover temporariamente."""
    if tipo == "Line":
        return {
            "bus0": n.lines.at[nome, "bus0"],
            "bus1": n.lines.at[nome, "bus1"],
            "length": n.lines.at[nome, "length"],
            "r": n.lines.at[nome, "r"],
            "x": n.lines.at[nome, "x"],
            "s_nom": n.lines.at[nome, "s_nom"],
        }
    else:
        return {
            "bus0": n.transformers.at[nome, "bus0"],
            "bus1": n.transformers.at[nome, "bus1"],
            "s_nom": n.transformers.at[nome, "s_nom"],
            "r": n.transformers.at[nome, "r"],
            "x": n.transformers.at[nome, "x"],
            "model": n.transformers.at[nome, "model"],
        }


def atribuir_slack_dinamico(n, buses_zona):
    """Se a zona (conjunto de barramentos) nao tiver nenhum gerador
    Slack, atribui esse papel ao maior gerador sincrono (por p_nom,
    entre hydro/fossil/biomass) presente nela. Devolve (nome_gerador,
    control_original) para poder ser reposto depois, ou (None, None)
    se ja havia Slack ou se nao houver nenhum gerador sincrono
    disponivel nessa zona."""
    gens_zona = n.generators[n.generators.bus.isin(buses_zona)]

    if (gens_zona.control == "Slack").any():
        return None, None  # ja tem Slack, nao mexe

    candidatos = gens_zona[gens_zona.carrier.isin(CARRIERS_COM_INERCIA)]
    if candidatos.empty:
        return None, None  # sem geradores sincronos disponiveis nesta zona

    maior = candidatos.p_nom.idxmax()
    control_original = n.generators.at[maior, "control"]
    n.generators.at[maior, "control"] = "Slack"
    return maior, control_original


for i, (tipo, elemento) in enumerate(elementos_a_testar, start=1):
    # -- 1. Guardar atributos originais e remover o elemento ------------
    atributos = obter_atributos(tipo, elemento)
    n.remove(tipo, elemento)
    n.determine_network_topology()

    # -- 2. Atribuir Slack dinamico a qualquer sub-rede que tenha ficado
    #       sem Slack apos esta remocao ------------------------------
    slacks_atribuidos = []  # [(nome_gerador, control_original), ...]
    zona_sem_geracao_sincrona = None

    for sub_id in n.buses["sub_network"].unique():
        buses_zona = n.buses[n.buses["sub_network"] == sub_id].index
        gerador, control_original = atribuir_slack_dinamico(n, buses_zona)
        if gerador is not None:
            slacks_atribuidos.append((gerador, control_original))
            print(f"    -> Slack reatribuido a '{gerador}' "
                  f"(sub-rede {sub_id}, {len(buses_zona)} barramentos)")
        else:
            gens_zona = n.generators[n.generators.bus.isin(buses_zona)]
            if not (gens_zona.control == "Slack").any() and \
               gens_zona[gens_zona.carrier.isin(CARRIERS_COM_INERCIA)].empty:
                zona_sem_geracao_sincrona = buses_zona

    if zona_sem_geracao_sincrona is not None:
        carga_zona = n.loads[n.loads.bus.isin(zona_sem_geracao_sincrona)]["p_set"].sum()
        resultados_n1.append({
            "tipo": tipo,
            "elemento": elemento,
            "resultado": "ILHA / PERDA DE ALIMENTACAO TOTAL",
            "detalhe": f"{len(zona_sem_geracao_sincrona)} barramento(s) sem "
                       f"nenhum gerador sincrono disponivel, carga: "
                       f"{carga_zona:.1f} MW",
            "n_violacoes": None,
            "pior_carregamento_pct": None,
        })
        print(f"  [{i}/{TOTAL_ELEMENTOS}] {elemento}: ILHA TOTAL "
              f"({len(zona_sem_geracao_sincrona)} barramentos, {carga_zona:.1f} MW)")

        # repor TODOS os controls ao estado original (nao so os que
        # julgamos ter mudado - ver nota antes do ciclo) + o elemento
        n.generators["control"] = CONTROLS_ORIGINAIS.copy()
        n.generators["p_set"] = P_SET_ORIGINAL.copy()
        n.add(tipo, elemento, **atributos)
        n.determine_network_topology()
        continue

    # -- 3. Correr o Power Flow AC (com o(s) Slack(s) ja garantido(s)) --
    try:
        convergiu, capados = resolver_pf_respeitando_capacidade(
            n, calcular_pesos_slack(n), DISTRIBUIR_SLACK, verbose=False
        )
    except Exception:
        convergiu = False

    reatribuicao_nota = (
        f" (com Slack reatribuido a {[g for g, _ in slacks_atribuidos]})"
        if slacks_atribuidos else ""
    )

    if not convergiu:
        resultados_n1.append({
            "tipo": tipo,
            "elemento": elemento,
            "resultado": "NAO CONVERGE",
            "detalhe": f"Power flow AC nao encontrou solucao{reatribuicao_nota}",
            "n_violacoes": None,
            "pior_carregamento_pct": None,
        })
        print(f"  [{i}/{TOTAL_ELEMENTOS}] {elemento}: NAO CONVERGE{reatribuicao_nota}")
    else:
        carregamento_linhas = (n.lines_t.p0.abs().iloc[0] / n.lines.s_nom * 100)
        carregamento_trafos = (
            n.transformers_t.p0.abs().iloc[0]
            / n.transformers.s_nom.replace(0, float("nan")) * 100
        )
        todos_carregamentos = pd.concat([carregamento_linhas, carregamento_trafos])
        violacoes = todos_carregamentos[todos_carregamentos > LIMIAR_VIOLACAO_PCT]

        if violacoes.empty:
            resultados_n1.append({
                "tipo": tipo,
                "elemento": elemento,
                "resultado": "OK",
                "detalhe": f"Sem violacoes{reatribuicao_nota}",
                "n_violacoes": 0,
                "pior_carregamento_pct": round(todos_carregamentos.max(), 2),
            })
            if i % 20 == 0 or i == TOTAL_ELEMENTOS:
                print(f"  [{i}/{TOTAL_ELEMENTOS}] {elemento}: OK "
                      f"(pior carregamento: {todos_carregamentos.max():.1f}%)"
                      f"{reatribuicao_nota}")
        else:
            pior = violacoes.sort_values(ascending=False)
            resultados_n1.append({
                "tipo": tipo,
                "elemento": elemento,
                "resultado": "SOBRECARGA",
                "detalhe": f"Pior: {pior.index[0]} a {pior.iloc[0]:.1f}%{reatribuicao_nota}",
                "n_violacoes": len(violacoes),
                "pior_carregamento_pct": round(pior.iloc[0], 2),
            })
            print(f"  [{i}/{TOTAL_ELEMENTOS}] {elemento}: SOBRECARGA "
                  f"({len(violacoes)} violacao(oes), pior: {pior.index[0]} "
                  f"a {pior.iloc[0]:.1f}%){reatribuicao_nota}")

    # -- 4. Repor: TODOS os controls e p_set ao estado original + o elemento
    n.generators["control"] = CONTROLS_ORIGINAIS.copy()
    n.generators["p_set"] = P_SET_ORIGINAL.copy()
    n.add(tipo, elemento, **atributos)
    n.determine_network_topology()


# ===========================================================================
# 5. RELATORIO FINAL DA ANALISE N-1
# ===========================================================================
df_n1 = pd.DataFrame(resultados_n1)

print("\n" + "=" * 60)
print("RESUMO DA ANALISE N-1")
print("=" * 60)
print(df_n1["resultado"].value_counts())

n_criticos = (df_n1["resultado"] != "OK").sum()
print(f"\n{n_criticos} de {len(df_n1)} elementos (linhas + transformadores) "
      f"causam algum tipo de violacao quando retirados individualmente.")

print("\nElementos criticos (por ordem de gravidade):")
ordem_gravidade = {
    "ILHA / PERDA DE ALIMENTACAO TOTAL": 0,
    "NAO CONVERGE": 1,
    "SOBRECARGA": 2,
    "OK": 3,
}
df_n1["_ordem"] = df_n1["resultado"].map(ordem_gravidade)
df_criticos = df_n1[df_n1["resultado"] != "OK"].sort_values(
    ["_ordem", "pior_carregamento_pct"], ascending=[True, False]
).drop(columns="_ordem")
print(df_criticos.to_string(index=False))

F_RESULTADO_N1 = RESULTADOS + f"resultados_N1_completo_{TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')}.csv"
df_n1.drop(columns="_ordem", errors="ignore").to_csv(F_RESULTADO_N1, index=False)
print(f"\nResultados completos guardados em: {F_RESULTADO_N1}")
