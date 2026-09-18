"""
rede_base.py - Construcao da rede RNT em PyPSA

Modulo partilhado por topologia.py, topologia_OPF.py e
contingencia_N1.py. Importa barramentos, linhas, transformadores,
cargas e geracao, e devolve a rede pronta a simular.

Nao inclui o desenho do mapa geografico nem o calculo dos fatores de
capacidade renovavel, que ficam nos scripts que deles precisam.
"""

import os
import pypsa
import pandas as pd

import types


def construir_rede(timestamp_cenario):
    """Constroi a rede RNT completa (barramentos, linhas,
    transformadores, cargas, geracao, importacao) para o instante
    indicado. Devolve um objeto com todas as variaveis que os
    scripts principais precisam (n, CAMINHO, DADOS, CENARIO_ATIVO,
    TIMESTAMP_CENARIO, _excel, barramentos, linhas, trafos, geracao).

    timestamp_cenario: string ou pd.Timestamp com a data/hora exata a
      simular (ex: "2024-01-08 19:45:00") - funciona para QUALQUER
      instante de 2024 presente no Excel da REN. A selecao do cenario
      e feita EXCLUSIVAMENTE por esta data/hora - nunca por nome."""

    # ---------------------------------------------------------------------------
    # 1. Caminhos dos ficheiros
    # ---------------------------------------------------------------------------
    # Pasta onde este ficheiro esta guardado.
    CAMINHO = os.path.dirname(os.path.abspath(__file__)) + os.sep

    # Dados de entrada: os cinco .csv exportados do QGIS e o registo
    # quarto-horario da REN.
    DADOS = os.path.join(CAMINHO, "dados") + os.sep

    f_barramentos = DADOS + "BarramentoRNT.csv"
    f_linhas = DADOS + "LinhasRNT.csv"
    f_trafos = DADOS + "TransformadoresRNT.csv"
    f_cargas = DADOS + "CargaRNT.csv"
    f_geracao = DADOS + "GeracaoRNT.csv"
    f_excel = DADOS + "Reparticao_da_Producao_20240101_20241231.xlsx"

    # ---------------------------------------------------------------------------
    # 2. Selecao do cenario a simular
    # ---------------------------------------------------------------------------
    # A carga de cada barramento e calculada a partir das colunas p_% e q/p
    # do CargaRNT.csv e dos valores de Consumo e Bombagem do instante:
    #   p_set = p_% * (Consumo + Bombagem)
    #   q_set = p_set * (q/p)

    TIMESTAMP_CENARIO = pd.Timestamp(timestamp_cenario)
    # Etiqueta usada nos prints e nos nomes dos ficheiros de saida.
    CENARIO_ATIVO = TIMESTAMP_CENARIO.strftime('%Y-%m-%d_%H%M')

    # Estacao do ano, que determina a coluna de s_nom a usar.
    mes = TIMESTAMP_CENARIO.month
    if mes in [12, 1, 2]:
        ESTACAO_ATIVA = "inv"       #inverno
    elif mes in [3, 4, 5]:
        ESTACAO_ATIVA = "prim"      #primavera
    elif mes in [6, 7, 8]:
        ESTACAO_ATIVA = "ver"       #verao
    else:
        ESTACAO_ATIVA = "out"       #outono

    # ---------------------------------------------------------------------------
    # 3. Registo quarto-horario da REN (Consumo, Bombagem, Importacao, Exportacao)
    # ---------------------------------------------------------------------------
    _excel = pd.read_excel(f_excel, header=2)
    _excel["Data e Hora"] = pd.to_datetime(_excel["Data e Hora"])
    _excel = _excel.set_index("Data e Hora")

    if TIMESTAMP_CENARIO not in _excel.index:
        raise ValueError(f"Timestamp {TIMESTAMP_CENARIO} nao encontrado no Excel. Verifica se a data e hora estao corretas.")

    CONSUMO_CENARIO = _excel.loc[TIMESTAMP_CENARIO, "Consumo"]
    BOMBAGEM_CENARIO = _excel.loc[TIMESTAMP_CENARIO, "Bombagem"]
    IMPORTACAO_CENARIO = _excel.loc[TIMESTAMP_CENARIO, "Importação"]
    EXPORTACAO_CENARIO = _excel.loc[TIMESTAMP_CENARIO, "Exportação"]

    print(f"Cenario ativo: {TIMESTAMP_CENARIO}")
    print(f"Estacao Termica assumida (s_nom): {ESTACAO_ATIVA}")
    print(f"  Consumo (Excel):    {CONSUMO_CENARIO:,.1f} MW")
    print(f"  Bombagem (Excel):   {BOMBAGEM_CENARIO:,.1f} MW")
    print(f"  Importacao (Excel): {IMPORTACAO_CENARIO:,.1f} MW")
    print(f"  Exportacao (Excel): {EXPORTACAO_CENARIO:,.1f} MW")

    # ---------------------------------------------------------------------------
    # 4. Criar a rede
    # ---------------------------------------------------------------------------
    n = pypsa.Network()
    n.name = "RNT_Portugal_Continental"

    # ---------------------------------------------------------------------------
    # 5. Barramentos (Bus)
    # ---------------------------------------------------------------------------
    barramentos = pd.read_csv(f_barramentos)

    n.add(
        "Bus",
        barramentos["name"],
        v_nom=barramentos["v_nom"].values,
        x=barramentos["x"].values,   # longitude
        y=barramentos["y"].values,   # latitude
    )

    # ---------------------------------------------------------------------------
    # 6. Linhas (Line)
    # ---------------------------------------------------------------------------
    linhas = pd.read_csv(f_linhas)

    S_BASE = 100  # MVA (fonte: Anexo B, Caracterizacao da RNT 31/12/2024)

    v_nom_bus = barramentos.set_index("name")["v_nom"]
    linhas["v_nom"] = linhas["bus0"].map(v_nom_bus)
    linhas["r_ohm"] = linhas["r"] * linhas["v_nom"] ** 2 / S_BASE
    linhas["x_ohm"] = linhas["x"] * linhas["v_nom"] ** 2 / S_BASE

    # Determina a coluna de s_nom correta baseada na estacao do ano
    coluna_s_nom = f"s_nom_{ESTACAO_ATIVA}"

    # Se a coluna sazonal nao existir, recorre a coluna generica.
    if coluna_s_nom not in linhas.columns:
        if ESTACAO_ATIVA in linhas.columns: # Caso a coluna se chame apenas "Inverno", "Verao"
            coluna_s_nom = ESTACAO_ATIVA
        else:
            print(f"\nAVISO: Coluna de capacidade {coluna_s_nom} nao encontrada em LinhasRNT.csv!")
            print("A utilizar a coluna padrao 's_nom'.")
            coluna_s_nom = "s_nom"

    n.add(
        "Line",
        linhas["name"],
        bus0=linhas["bus0"].values,
        bus1=linhas["bus1"].values,
        length=linhas["length"].values,   # km
        r=linhas["r_ohm"].values,         # Ohm (convertido de p.u.)
        x=linhas["x_ohm"].values,         # Ohm (convertido de p.u.)
        s_nom=linhas[coluna_s_nom].values,# MVA da estacao correta
    )

    # ---------------------------------------------------------------------------
    # 7. Transformadores (Transformer)
    # ---------------------------------------------------------------------------
    trafos = pd.read_csv(f_trafos)

    n.add(
        "Transformer",
        trafos["name"],
        bus0=trafos["bus0"].values,
        bus1=trafos["bus1"].values,
        s_nom=trafos["s_nom"].values,   # MVA (base propria do trafo)
        r=trafos["R"].values,           # p.u. na base s_nom do trafo
        x=trafos["X"].values,           # p.u. na base s_nom do trafo
        model=trafos["model"].values,
    )

    # ---------------------------------------------------------------------------
    # 8. Cargas (Load)
    # ---------------------------------------------------------------------------
    cargas = pd.read_csv(f_cargas)

    total_carga_cenario = CONSUMO_CENARIO + BOMBAGEM_CENARIO
    p_set_cargas = pd.Series(
        (cargas["p_%"] * total_carga_cenario).values, index=cargas["name"].values
    )
    q_set_cargas = p_set_cargas.values * cargas["q/p"].values
    print(f"  Carga total distribuida pelos barramentos: {p_set_cargas.sum():,.1f} MW")

    n.add(
        "Load",
        cargas["name"],
        bus=cargas["bus"].values,
        p_set=p_set_cargas.values,
        q_set=q_set_cargas,
    )

    # ---------------------------------------------------------------------------
    # 9. Geracao (Generator)
    # ---------------------------------------------------------------------------
    geracao = pd.read_csv(f_geracao)

    if "Q_total" in geracao.columns:
        q_set_geradores = geracao["Q_total"].values
    else:
        print("\nAVISO: coluna 'Q_total' nao encontrada em GeracaoRNT.csv - "
              "a assumir q_set = 0 para todos os geradores.")
        q_set_geradores = 0.0

    n.add(
        "Generator",
        geracao["name"],
        bus=geracao["bus"].values,
        p_nom=geracao["P_total"].values,   # MW
        control=geracao["control"].values, # Slack / PV / PQ
        carrier=geracao["Carrier"].values, # solar, hydro, wind, fossil, biomass, import
        q_set=q_set_geradores,             # MVAr
    )

    # Os custos marginais sao definidos em topologia_OPF.py.

    # ---------------------------------------------------------------------------
    # 9.1 Importacao - injecao fixa nos barramentos de fronteira
    # ---------------------------------------------------------------------------
    importadores = geracao[geracao["Carrier"] == "import"]["name"].tolist()

    if len(importadores) == 0:
        print("\nAVISO: nenhum gerador com Carrier == 'import' encontrado em "
              "GeracaoRNT.csv - a importacao nao sera injetada na rede.")
    else:
        importacao_por_bus = IMPORTACAO_CENARIO / len(importadores)
        n.generators.loc[importadores, "p_nom"] = importacao_por_bus
        n.generators.loc[importadores, "p_min_pu"] = 1.0
        n.generators.loc[importadores, "p_max_pu"] = 1.0
        print(f"\nImportacao: {IMPORTACAO_CENARIO:,.1f} MW distribuida por "
              f"{len(importadores)} barramentos de fronteira "
              f"({importacao_por_bus:,.1f} MW cada): {importadores}")

    # ---------------------------------------------------------------------------
    # 9.2 Exportacao - carga fixa nos mesmos barramentos de fronteira
    # ---------------------------------------------------------------------------
    # A exportacao e adicionada como Load, distribuida em partes iguais
    # pelos mesmos barramentos de fronteira. Fica fora de p_set_cargas,
    # mantendo p_set fixo na compensacao iterativa de perdas.
    if len(importadores) == 0:
        print("\nAVISO: sem geradores de importacao identificados - a "
              "exportacao tambem nao sera injetada na rede.")
    else:
        exportadores_bus = n.generators.loc[importadores, "bus"].values
        exportadores_nome = [nome.replace("_IMPORT", "_EXPORT") for nome in importadores]
        exportacao_por_bus = EXPORTACAO_CENARIO / len(importadores)

        n.add(
            "Load",
            exportadores_nome,
            bus=exportadores_bus,
            p_set=exportacao_por_bus,
        )
        print(f"Exportacao: {EXPORTACAO_CENARIO:,.1f} MW distribuida por "
              f"{len(exportadores_nome)} barramentos de fronteira "
              f"({exportacao_por_bus:,.1f} MW cada): {exportadores_nome}")

    # ---------------------------------------------------------------------------
    # 10. Verificacoes
    # ---------------------------------------------------------------------------
    n.lines.loc[n.lines.r == 0, "r"] = 0.00001
    n.lines.loc[n.lines.x == 0, "x"] = 0.00001
    n.transformers.loc[n.transformers.r == 0, "r"] = 0.00001
    n.transformers.loc[n.transformers.x == 0, "x"] = 0.00001

    n.sanitize()
    n.consistency_check()

    # ---------------------------------------------------------------------------
    # 10.1 Conectividade e barramento Slack
    # ---------------------------------------------------------------------------
    n.determine_network_topology()
    print(f"\nNumero de sub-redes (subnetworks) detetadas: {len(n.sub_networks)}")
    if len(n.sub_networks) > 1:
        print("AVISO: a rede tem mais que uma sub-rede ligada - verificar se "
              "cada uma tem o seu proprio gerador Slack antes de correr n.pf().")

    slacks = n.generators[n.generators.control == "Slack"]
    print(f"Geradores Slack definidos: {len(slacks)} -> {list(slacks.index)}")
    if len(slacks) != 1:
        print("AVISO: era esperado exatamente 1 gerador Slack para uma rede "
              "totalmente ligada - confirmar GeracaoRNT.csv.")

    print(n)

    print("\nBarramentos:", len(n.buses))
    print("Linhas:", len(n.lines))
    print("Transformadores:", len(n.transformers))
    print("Cargas:", len(n.loads))
    print("Geradores:", len(n.generators))
    print("\nCarga total (MW):", n.loads.p_set.sum())
    print("Potencia instalada total (MW):", n.generators.p_nom.sum())

    return types.SimpleNamespace(
        n=n,
        CAMINHO=CAMINHO,
        DADOS=DADOS,
        CENARIO_ATIVO=CENARIO_ATIVO,
        TIMESTAMP_CENARIO=TIMESTAMP_CENARIO,
        _excel=_excel,
        barramentos=barramentos,
        linhas=linhas,
        trafos=trafos,
        geracao=geracao,
        p_set_cargas=p_set_cargas,
    )


def resolver_pf_respeitando_capacidade(n, pesos_slack_todos, distribuir_slack,
                                        max_iter=10, verbose=True):
    """Executa n.pf() com Slack distribuido, mas ao contrario da chamada
    direta ao PyPSA, verifica apos cada resolucao se algum gerador
    elegivel ficou acima da sua propria capacidade instalada (p_nom) -
    algo que a formula proporcional do PyPSA, por si so, nao impede.

    Isto aproxima o comportamento real de saturacao de um regulador de
    velocidade: quando uma central ja nao tem margem, o excedente que
    lhe seria pedido tem de ser assumido pelas restantes centrais
    elegiveis com margem disponivel, nao pela central ja saturada.

    Cada gerador que exceda a sua capacidade e fixado exatamente nela
    (retirado da repartiacao seguinte, atribuindo-lhe peso zero), e os
    pesos das restantes sao recalculados, repetindo o processo ate
    nenhuma exceder o limite, ou ate todas as elegiveis estarem
    saturadas (nesse caso, a fisicamente impossivel, devolve
    convergiu=False).

    Partilhada pelos tres scripts principais (topologia.py,
    topologia_OPF.py, contingencia_N1.py), todos usando o mesmo
    mecanismo de Slack distribuido.

    Devolve (convergiu, nomes_dos_geradores_capados)."""
    capados = set()
    pesos_atuais = pesos_slack_todos.copy()

    for tentativa in range(1, max_iter + 1):
        pesos_slack = {}
        for sub_id in n.sub_networks.index:
            buses_sub = n.buses[n.buses.sub_network == sub_id].index
            gens_sub = n.generators[n.generators.bus.isin(buses_sub)].index
            pesos_slack[sub_id] = pesos_atuais[gens_sub]

        resultado_pf = n.pf(
            distribute_slack=distribuir_slack,
            slack_weights=pesos_slack if distribuir_slack else "p_set",
        )
        convergiu = bool(resultado_pf.converged.iloc[0, 0]) \
            if hasattr(resultado_pf.converged, "iloc") else bool(resultado_pf.converged)
        if not convergiu:
            return False, capados

        despacho_pos_pf = n.generators_t.p.iloc[0]
        elegiveis = pesos_atuais[pesos_atuais > 0].index
        excesso = (despacho_pos_pf[elegiveis] - n.generators.loc[elegiveis, "p_nom"]).clip(lower=0)
        excedem = excesso[excesso > 1e-3].index  # tolerancia de 1 kW, ruido numerico

        if len(excedem) == 0:
            if verbose and capados:
                print(f"  Limite de capacidade respeitado apos redistribuir "
                      f"o excedente de: {sorted(capados)}")
            return True, capados

        capados.update(excedem)
        if verbose:
            print(f"  AVISO: {list(excedem)} excederam a capacidade instalada "
                  f"em {excesso[excedem].round(1).to_dict()} MW - a fixar no "
                  f"limite e a redistribuir pelas restantes.")

        n.generators.loc[excedem, "p_set"] = n.generators.loc[excedem, "p_nom"]
        pesos_atuais[excedem] = 0.0

        if (pesos_atuais > 0).sum() == 0:
            if verbose:
                print("  AVISO: todas as tecnologias elegiveis estao "
                      "saturadas na sua capacidade - fisicamente "
                      "impossivel cobrir o desequilibrio remanescente.")
            return False, capados

    if verbose:
        print(f"  AVISO: nao estabilizou em {max_iter} tentativas de "
              f"redistribuicao do excedente.")
    return False, capados

