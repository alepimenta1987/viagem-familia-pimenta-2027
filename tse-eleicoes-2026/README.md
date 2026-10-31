# Votos após as 17h — Presidente 2026 (TSE)

Pipeline que baixa os dados oficiais do TSE do 1º turno (04/10/2026) e do 2º turno
(25/10/2026), grava num banco SQLite e conta quantos votos foram computados
depois do encerramento da votação (17h, horário de Brasília).

## Como rodar

```bash
# sem dependências externas: só a biblioteca padrão do Python 3.9+

python tse.py logs        # arquivos de urna (logs) de todas as UFs + exterior, 1º e 2º turno
python tse.py votacao     # votação por seção para Presidente (conferência)
python tse.py analisar    # relatório em resultados/relatorio.md + CSVs
```

Teste rápido com uma UF: `python tse.py logs --turnos 1 --ufs AC`.
A carga é retomável: UFs já carregadas são puladas (use `--refazer` para recarregar).
Os zips são apagados depois de processados (use `--manter-zip` para guardá-los).

**Volume:** os arquivos de urna somam dezenas de GB por turno (SP sozinho tem vários GB).
Só um zip por vez fica em disco; o banco final fica com algumas centenas de MB.

## Fontes

| Dado | URL (padrão; ajustável por `--url-urna` / `--url-votacao`) |
|---|---|
| Arquivos de urna (BU, log, RDV) por UF | `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/arqurnatot/bu_imgbu_logjez_rdv_vscmr_2026_{1t,2t}_{UF}.zip` |
| Votação por seção — Presidente | `https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2026_BR.zip` |

Os nomes seguem o padrão publicado pelo TSE em 2022; se o TSE mudar o padrão em 2026,
basta passar a URL nova (com `{ano}`, `{turno}` e `{uf}`) nas opções acima.

## Metodologia

- O horário de cada voto vem do **log da urna** (`logd.dat` dentro de cada `.logjez`):
  cada linha `O voto do eleitor foi computado` é um eleitor que votou (no 2º turno, um
  voto para Presidente; no 1º turno, o eleitor votou em todos os cargos, inclusive Presidente).
  Só contam as linhas com a data do dia da eleição (o log também guarda eventos da carga da urna).
- O BU e a planilha de votação por seção não têm horário — por isso o log é a única fonte possível.
- **Fuso horário:** o relógio das urnas segue a hora local. Em vez de usar uma tabela fixa
  (o Amazonas, por exemplo, tem municípios em dois fusos), o script detecta o fuso de cada
  município pela mediana do horário do primeiro voto das seções (a votação abre às 8h de
  Brasília). Ex.: no Acre o primeiro voto sai por volta de 06:00 no relógio da urna → +2h;
  15:00 no Acre = 17:00 em Brasília. No exterior (UF `ZZ`) a abertura é às 8h locais, então
  o corte vira 17h locais.
- O relatório traz também a contagem ingênua "relógio da urna ≥ 17h", só para comparação.
- **Conferência:** o total de votos do log por seção é comparado ao comparecimento oficial
  (`QT_COMPARECIMENTO`) do arquivo de votação por seção.

Votar depois das 17h é previsto em lei: quem já estava na fila no encerramento recebe senha
e vota (Código Eleitoral, art. 153). Os números mostram o tamanho dessas filas, não irregularidades.

## Banco (`eleicoes2026.sqlite`)

| Tabela | Conteúdo |
|---|---|
| `secao` | uma linha por seção/turno: total de votos no log, primeiro e último voto |
| `votos_hora` | votos por hora cheia do relógio da urna, por seção |
| `fuso_municipio` | diferença detectada entre o relógio das urnas e Brasília, por município |
| `votacao_secao` | votação oficial por seção para Presidente (candidato, votos, aptos, comparecimento) |
| `carga` | controle das UFs já carregadas |

Exemplo de consulta:

```sql
SELECT v.turno, SUM(v.votos) AS votos_apos_17h
FROM votos_hora v JOIN fuso_municipio f USING (turno, uf, cd_municipio)
WHERE v.hora + f.offset_h >= 17
GROUP BY v.turno;
```

`test_pipeline.py` roda o fluxo inteiro com arquivos sintéticos no formato do TSE
(`python -m unittest test_pipeline.py`).
