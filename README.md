# Modelo da Rede Nacional de Transporte (RNT) em PyPSA

Modelo computacional da Rede Nacional de Transporte de eletricidade portuguesa,
construído exclusivamente a partir de dados de acesso público e implementado em
[PyPSA](https://pypsa.org).

Desenvolvido no âmbito de uma dissertação de Mestrado Integrado em Engenharia
Eletrotécnica e de Computadores.

## O modelo

| Componente | Quantidade |
|---|---|
| Barramentos | 212 |
| Linhas | 347 (9 660,6 km) |
| Transformadores | 38 |
| Geradores | 596 |
| Cargas | 88 |

Níveis de tensão modelados: 150, 220 e 400 kV. A rede de distribuição (60 kV e
inferior) fica fora do âmbito.

## Fontes de dados

Todos os dados são de acesso público:

- **REN**, *Caracterização da RNT para Efeitos de Acesso à Rede* — topologia,
  parâmetros elétricos das linhas e transformadores, e perfis de carga por
  subestação
- **REN Data Hub** — registo quarto-horário de 2024 (consumo, bombagem,
  produção por tecnologia, importação e exportação)
- **DGEG** — capacidade instalada de produção, por município e por tecnologia
- **OpenStreetMap** e **Open Infrastructure Map** — traçado geográfico das linhas
- **ERA5** (via [atlite](https://atlite.readthedocs.io)) — dados meteorológicos
  para o cálculo do fator de capacidade eólico e solar

## Estrutura

```
rede_base.py          Construção da rede, partilhada pelos três scripts abaixo
topologia.py          Despacho real imposto + trânsito de potências não linear
topologia_OPF.py      Despacho económico (OPF) + compensação iterativa de perdas
contingencia_N1.py    Análise de contingência N-1 a linhas e transformadores

rnt-qgis/                 Projeto QGIS onde a topologia foi georreferenciada
dados/                Ficheiros de entrada (ver abaixo)
resultados/           Mapas, gráficos e tabelas gerados (criada automaticamente)
cache/                Dados do ERA5 e redes em NetCDF (criada automaticamente)
```

Os três scripts de simulação chamam `rede_base.construir_rede(timestamp)` e
recebem a rede pronta, evitando duplicar essa lógica.

### Ficheiros de entrada (pasta `dados/`)

```
BarramentoRNT.csv         Barramentos (nome, nível de tensão, coordenadas)
LinhasRNT.csv             Linhas (extremos, comprimento, R, X, s_nom sazonal)
TransformadoresRNT.csv    Transformadores (extremos, s_nom, R, X)
CargaRNT.csv              Carga por barramento (fração do total nacional, q/p)
GeracaoRNT.csv            Geradores (barramento, capacidade, tecnologia, controlo)
precos_gas_2024.csv       Preço diário do gás natural (usado apenas no OPF)

Reparticao_da_Producao_20240101_20241231.xlsx
                          Registo quarto-horário de 2024, do REN Data Hub
```

Os cinco primeiros `.csv` são exportados do QGIS, onde a topologia foi
georreferenciada. Os dados da DGEG são usados nessa fase, para construir o
`GeracaoRNT.csv`, e não entram diretamente na execução dos scripts.

## Instalação

Recomenda-se o conda: o PyPSA e o atlite dependem de bibliotecas
geoespaciais que o conda resolve com menos atrito do que o pip.

```bash
git clone https://github.com/<utilizador>/<repositorio>.git
cd <repositorio>
conda env create -f environment.yml
conda activate rnt-pypsa
```

Em alternativa, com pip:

```bash
pip install -r requirements.txt
```

Testado com Python 3.11 e PyPSA 1.2.4. O solver por omissão é o HiGHS,
incluído com o PyPSA. O Gurobi é opcional, usado apenas no diagnóstico
de inviabilidade do despacho ótimo, e requer licença própria.

## Utilização

Cada script tem, no topo, um bloco `OPÇÕES DE SIMULAÇÃO` com a data/hora do
cenário a simular e os interruptores das etapas opcionais:

```python
TIMESTAMP_CENARIO_ALVO = "2024-01-08 19:45:00"
```

Funciona para qualquer instante de 2024 presente no registo da REN. Depois:

```bash
python topologia.py           # despacho real
python topologia_OPF.py       # despacho ótimo
python contingencia_N1.py     # análise N-1
```

A primeira execução descarrega os dados do ERA5 através do atlite, o que pode
demorar alguns minutos e exige uma conta gratuita no
[CDS](https://cds.climate.copernicus.eu). As execuções seguintes reutilizam o
ficheiro em cache.

## Resultados

Cada script produz, na pasta de trabalho, um mapa estático de congestionamento,
um mapa interativo em HTML, e um gráfico do balanço energético. A análise N-1
exporta ainda um `.csv` com o resultado de cada elemento testado.

## Licença

O código deste repositório é distribuído sob a licença MIT (ver `LICENSE`).

Os dados incluídos provêm de fontes públicas de terceiros, cada uma com as
suas próprias condições de utilização, definidas pelas entidades que os
publicam: REN, DGEG, OpenStreetMap, Open Infrastructure Map e ERA5/Copernicus.
A licença MIT aplica-se ao código, não a esses dados.
