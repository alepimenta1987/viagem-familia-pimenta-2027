#!/usr/bin/env python3
"""Baixa os arquivos de urna e a votação por seção das eleições presidenciais
de 2026 no TSE, carrega tudo num banco SQLite e mede quantos votos foram
computados depois do encerramento da votação (17h, horário de Brasília).

Uso:
    python tse.py logs      [--turnos 1 2] [--ufs SP RJ ...]   # arquivos de urna -> banco
    python tse.py votacao                                     # votação por seção (Presidente) -> banco
    python tse.py analisar                                    # gera o relatório em resultados/
"""

import argparse
import csv
import io
import os
import re
import sqlite3
import statistics
import sys
import time
import urllib.request
import zipfile
from collections import Counter, defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import py7zr
import py7zr.io

ANO = 2026
DATAS_TURNO = {1: "04/10/2026", 2: "25/10/2026"}
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
       "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]

URL_URNA = ("https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/arqurnatot/"
            "bu_imgbu_logjez_rdv_vscmr_{ano}_{turno}t_{uf}.zip")
URL_VOTACAO = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_{ano}_BR.zip"

ABERTURA_H = 8   # abertura das seções, horário de Brasília
FECHAMENTO_H = 17  # encerramento, horário de Brasília

AQUI = Path(__file__).resolve().parent
MSG_VOTO = "O voto do eleitor foi computado"
RE_SECAO = re.compile(r"-(\d{5})(\d{4})(\d{4})\.logjez$", re.IGNORECASE)


# ---------------------------------------------------------------- download

def baixar(url, destino, tentativas=5):
    """Download com retomada (HTTP Range) e novas tentativas."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".part")
    if destino.exists():
        return destino
    for tentativa in range(tentativas):
        inicio = parcial.stat().st_size if parcial.exists() else 0
        req = urllib.request.Request(url, headers={"User-Agent": "tse-analise/1.0"})
        if inicio:
            req.add_header("Range", f"bytes={inicio}-")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                if inicio and resp.status != 206:
                    inicio = 0  # servidor ignorou o Range: recomeça
                total = int(resp.headers.get("Content-Length", 0)) + inicio
                with open(parcial, "ab" if inicio else "wb") as f:
                    baixado = inicio
                    while bloco := resp.read(1 << 20):
                        f.write(bloco)
                        baixado += len(bloco)
                        if total:
                            print(f"\r  {destino.name}: {baixado / 1e6:,.0f} / {total / 1e6:,.0f} MB",
                                  end="", flush=True)
            print()
            parcial.rename(destino)
            return destino
        except Exception as e:  # noqa: BLE001 - rede instável: tenta de novo
            espera = 2 ** (tentativa + 1)
            print(f"\n  falha ao baixar {url}: {e}; nova tentativa em {espera}s", file=sys.stderr)
            time.sleep(espera)
    raise RuntimeError(f"não foi possível baixar {url}")


# ---------------------------------------------------------------- logs de urna

def ler_logjez(dados):
    """Extrai o texto dos logs (.dat) de um arquivo .logjez (formato 7z)."""
    with py7zr.SevenZipFile(io.BytesIO(dados), "r") as z:
        fab = py7zr.io.BytesIOFactory(limit=1 << 30)
        z.extractall(factory=fab)
    textos = []
    for nome, prod in fab.products.items():
        if nome.lower().endswith(".dat"):
            prod.seek(0)
            textos.append(prod.read().decode("latin-1"))
    return textos


def contar_votos(textos, data_eleicao):
    """Retorna (Counter hora -> votos, primeiro, último) dos votos do dia da eleição."""
    por_hora = Counter()
    horarios = []
    for texto in textos:
        for linha in texto.splitlines():
            if MSG_VOTO not in linha:
                continue
            campos = linha.split("\t")
            # campos: "dd/mm/aaaa hh:mm:ss", nível, id urna, aplicação, mensagem, hash
            data, _, hora = campos[0].partition(" ")
            if data != data_eleicao or len(hora) < 8:
                continue
            por_hora[int(hora[:2])] += 1
            horarios.append(hora[:8])
    if not horarios:
        return por_hora, None, None
    return por_hora, min(horarios), max(horarios)


def processar_logjez(args):
    nome, dados, data_eleicao = args
    m = RE_SECAO.search(os.path.basename(nome))
    if not m:
        return nome, None, f"nome não reconhecido: {nome}"
    try:
        por_hora, primeiro, ultimo = contar_votos(ler_logjez(dados), data_eleicao)
    except Exception as e:  # noqa: BLE001 - arquivo corrompido não interrompe a carga
        return nome, None, f"{nome}: {e}"
    municipio, zona, secao = (int(g) for g in m.groups())
    return nome, (municipio, zona, secao, dict(por_hora), primeiro, ultimo), None


def iterar_logjez(zf):
    """Percorre os .logjez de um zip (inclusive zips aninhados)."""
    for info in zf.infolist():
        nome = info.filename.lower()
        if nome.endswith(".logjez"):
            yield info.filename, zf.read(info)
        elif nome.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(zf.read(info))) as interno:
                yield from iterar_logjez(interno)


def map_limitado(pool, func, itens, janela=1024):
    """Como pool.map, mas sem consumir o iterável inteiro de uma vez (limita a memória)."""
    pendentes = deque()
    for item in itens:
        pendentes.append(pool.submit(func, item))
        if len(pendentes) >= janela:
            yield pendentes.popleft().result()
    while pendentes:
        yield pendentes.popleft().result()


def gravar_secoes(con, turno, uf, lote):
    con.executemany(
        "INSERT OR REPLACE INTO secao VALUES (?,?,?,?,?,?,?,?)",
        [(turno, uf, mu, zo, se, sum(h.values()), pri, ult) for mu, zo, se, h, pri, ult in lote])
    con.executemany(
        "DELETE FROM votos_hora WHERE turno=? AND uf=? AND cd_municipio=? AND nr_zona=? AND nr_secao=?",
        [(turno, uf, mu, zo, se) for mu, zo, se, *_ in lote])
    con.executemany(
        "INSERT INTO votos_hora VALUES (?,?,?,?,?,?,?)",
        [(turno, uf, mu, zo, se, hora, n) for mu, zo, se, h, *_ in lote for hora, n in h.items()])


def carregar_uf(con, caminho_zip, turno, uf, processos):
    data_eleicao = DATAS_TURNO[turno]
    arquivos = erros = 0
    lote = []
    with zipfile.ZipFile(caminho_zip) as zf, ProcessPoolExecutor(processos) as pool:
        tarefas = ((nome, dados, data_eleicao) for nome, dados in iterar_logjez(zf))
        for nome, res, erro in map_limitado(pool, processar_logjez, tarefas):
            arquivos += 1
            if erro:
                erros += 1
                print(f"  aviso: {erro}", file=sys.stderr)
                continue
            lote.append(res)
            if len(lote) >= 2000:
                gravar_secoes(con, turno, uf, lote)
                lote.clear()
                print(f"\r  {uf} {turno}º turno: {arquivos:,} logs", end="", flush=True)
    gravar_secoes(con, turno, uf, lote)
    con.execute("INSERT OR REPLACE INTO carga VALUES (?,?,?,?,?)",
                (turno, uf, arquivos, erros, datetime.now().isoformat(timespec="seconds")))
    con.commit()
    print(f"\r  {uf} {turno}º turno: {arquivos:,} logs ({erros} com erro)")


def cmd_logs(a):
    con = conectar(a.banco)
    for turno in a.turnos:
        for uf in a.ufs:
            if not a.refazer and con.execute(
                    "SELECT 1 FROM carga WHERE turno=? AND uf=?", (turno, uf)).fetchone():
                print(f"{uf} {turno}º turno já carregado (use --refazer para recarregar)")
                continue
            url = a.url_urna.format(ano=a.ano, turno=turno, uf=uf)
            caminho = baixar(url, Path(a.dir_download) / os.path.basename(url))
            carregar_uf(con, caminho, turno, uf, a.processos)
            if not a.manter_zip:
                caminho.unlink()


# ---------------------------------------------------------------- votação por seção

COLUNAS_VOTACAO = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                   "CD_CARGO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS", "QT_APTOS",
                   "QT_COMPARECIMENTO", "QT_ABSTENCOES"]


def cmd_votacao(a):
    con = conectar(a.banco)
    url = a.url_votacao.format(ano=a.ano)
    caminho = baixar(url, Path(a.dir_download) / os.path.basename(url))
    con.execute("DELETE FROM votacao_secao")
    with zipfile.ZipFile(caminho) as zf:
        for nome in zf.namelist():
            if not nome.lower().endswith(".csv"):
                continue
            print(f"  carregando {nome}")
            with zf.open(nome) as bruto:
                leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""),
                                    delimiter=";")
                cabecalho = next(leitor)
                idx = [cabecalho.index(c) if c in cabecalho else None for c in COLUNAS_VOTACAO]
                i_cargo = idx[COLUNAS_VOTACAO.index("CD_CARGO")]
                lote = []
                for linha in leitor:
                    if i_cargo is not None and linha[i_cargo] != "1":  # 1 = Presidente
                        continue
                    lote.append([linha[i] if i is not None else None for i in idx])
                    if len(lote) >= 50_000:
                        con.executemany(f"INSERT INTO votacao_secao VALUES ({','.join('?' * 13)})", lote)
                        lote.clear()
                con.executemany(f"INSERT INTO votacao_secao VALUES ({','.join('?' * 13)})", lote)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM votacao_secao").fetchone()[0]
    print(f"votacao_secao: {n:,} linhas")
    if not a.manter_zip:
        caminho.unlink()


# ---------------------------------------------------------------- análise

def segundos(hhmmss):
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def detectar_fusos(con):
    """Detecta, por município, a diferença entre o relógio das urnas e Brasília.

    A votação abre às 8h de Brasília; a mediana do horário do primeiro voto das
    seções de um município fica poucos minutos depois da abertura no relógio
    local das urnas. Ex.: no Acre a mediana fica perto de 06:0x -> offset +2.
    Municípios com menos de 5 seções usam a mediana da UF.
    """
    con.execute("DELETE FROM fuso_municipio")
    linhas = con.execute(
        "SELECT turno, uf, cd_municipio, primeiro_voto FROM secao WHERE primeiro_voto IS NOT NULL")
    por_mun, por_uf = defaultdict(list), defaultdict(list)
    for turno, uf, mun, pri in linhas:
        s = segundos(pri)
        por_mun[(turno, uf, mun)].append(s)
        por_uf[(turno, uf)].append(s)

    def offset(amostra):
        return round((ABERTURA_H * 3600 - statistics.median(amostra)) / 3600)

    off_uf = {k: offset(v) for k, v in por_uf.items()}
    con.executemany("INSERT INTO fuso_municipio VALUES (?,?,?,?)", [
        (t, uf, mun, offset(v) if len(v) >= 5 else off_uf[(t, uf)])
        for (t, uf, mun), v in por_mun.items()])
    con.commit()


CONSULTAS = {
    "resumo_turno": """
        SELECT v.turno,
               SUM(v.votos)                                                  AS votos_log,
               SUM(CASE WHEN v.hora + f.offset_h >= :fecha THEN v.votos END) AS votos_apos_17h_brasilia,
               ROUND(100.0 * SUM(CASE WHEN v.hora + f.offset_h >= :fecha THEN v.votos END)
                     / SUM(v.votos), 3)                                      AS pct_apos_17h,
               SUM(CASE WHEN v.hora >= :fecha THEN v.votos END)              AS votos_apos_17h_relogio_local
        FROM votos_hora v JOIN fuso_municipio f USING (turno, uf, cd_municipio)
        GROUP BY v.turno ORDER BY v.turno""",
    "por_uf": """
        SELECT v.turno, v.uf, MIN(f.offset_h) AS offset_min_h, MAX(f.offset_h) AS offset_max_h,
               SUM(v.votos) AS votos_log,
               SUM(CASE WHEN v.hora + f.offset_h >= :fecha THEN v.votos END) AS votos_apos_17h_brasilia,
               ROUND(100.0 * SUM(CASE WHEN v.hora + f.offset_h >= :fecha THEN v.votos END)
                     / SUM(v.votos), 3) AS pct_apos_17h
        FROM votos_hora v JOIN fuso_municipio f USING (turno, uf, cd_municipio)
        GROUP BY v.turno, v.uf ORDER BY v.turno, votos_apos_17h_brasilia DESC""",
    "por_hora_brasilia": """
        SELECT v.turno, v.hora + f.offset_h AS hora_brasilia, SUM(v.votos) AS votos
        FROM votos_hora v JOIN fuso_municipio f USING (turno, uf, cd_municipio)
        WHERE v.uf <> 'ZZ'
        GROUP BY v.turno, hora_brasilia ORDER BY v.turno, hora_brasilia""",
    "secoes_com_votos_apos_17h": """
        WITH tardios AS (
            SELECT v.turno, v.uf, v.cd_municipio, v.nr_zona, v.nr_secao, SUM(v.votos) AS votos_tardios
            FROM votos_hora v JOIN fuso_municipio f USING (turno, uf, cd_municipio)
            WHERE v.hora + f.offset_h >= :fecha
            GROUP BY 1, 2, 3, 4, 5)
        SELECT s.turno, COUNT(*) AS secoes_total, COUNT(t.votos_tardios) AS secoes_com_voto_apos_17h,
               ROUND(100.0 * COUNT(t.votos_tardios) / COUNT(*), 2) AS pct_secoes,
               MAX(t.votos_tardios) AS max_votos_tardios_numa_secao
        FROM secao s LEFT JOIN tardios t USING (turno, uf, cd_municipio, nr_zona, nr_secao)
        GROUP BY s.turno ORDER BY s.turno""",
    "ultimos_votos": """
        SELECT s.turno, s.uf, s.cd_municipio, s.nr_zona, s.nr_secao, s.ultimo_voto AS ultimo_voto_relogio_urna,
               printf('%02d', CAST(substr(s.ultimo_voto, 1, 2) AS INTEGER) + f.offset_h)
                   || substr(s.ultimo_voto, 3) AS ultimo_voto_brasilia, s.votos_total
        FROM secao s JOIN fuso_municipio f USING (turno, uf, cd_municipio)
        WHERE s.uf <> 'ZZ'
        ORDER BY s.turno, CAST(substr(s.ultimo_voto, 1, 2) AS INTEGER) + f.offset_h DESC,
                 substr(s.ultimo_voto, 3) DESC
        LIMIT 50""",
    "conferencia_comparecimento": """
        WITH tse AS (
            SELECT turno, uf, cd_municipio, nr_zona, nr_secao, MAX(qt_comparecimento) AS comparecimento
            FROM votacao_secao GROUP BY 1, 2, 3, 4, 5)
        SELECT s.turno, COUNT(*) AS secoes_log, COUNT(tse.comparecimento) AS secoes_casadas,
               SUM(s.votos_total) AS votos_log, SUM(tse.comparecimento) AS comparecimento_tse,
               SUM(CASE WHEN s.votos_total <> tse.comparecimento THEN 1 ELSE 0 END) AS secoes_divergentes
        FROM secao s LEFT JOIN tse USING (turno, uf, cd_municipio, nr_zona, nr_secao)
        GROUP BY s.turno ORDER BY s.turno""",
}


def tabela_md(cursor):
    cols = [d[0] for d in cursor.description]
    linhas = cursor.fetchall()
    def fmt(col, v):
        if v is None:
            return ""
        if isinstance(v, int) and not col.startswith(("cd_", "nr_", "turno", "hora", "offset")):
            return f"{v:,}".replace(",", ".")
        return str(v)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(fmt(c, v) for c, v in zip(cols, l)) + " |" for l in linhas]
    return cols, linhas, "\n".join(out)


def cmd_analisar(a):
    con = conectar(a.banco)
    if not con.execute("SELECT 1 FROM secao LIMIT 1").fetchone():
        sys.exit("banco sem dados de log de urna: rode antes 'python tse.py logs'")
    detectar_fusos(con)
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    relatorio = [f"# Votos computados após as 17h — Presidente {a.ano}", "",
                 f"Gerado em {datetime.now():%d/%m/%Y %H:%M} a partir de `{a.banco}`.", ""]
    tem_votacao = con.execute("SELECT 1 FROM votacao_secao LIMIT 1").fetchone()
    for nome, sql in CONSULTAS.items():
        if nome == "conferencia_comparecimento" and not tem_votacao:
            continue
        cols, linhas, md = tabela_md(con.execute(sql, {"fecha": FECHAMENTO_H}))
        with open(saida / f"{nome}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(linhas)
        relatorio += [f"## {nome.replace('_', ' ')}", "", md, ""]
    (saida / "relatorio.md").write_text("\n".join(relatorio), encoding="utf-8")
    print("\n".join(relatorio))
    print(f"\nCSVs e relatorio.md gravados em {saida}/")


# ---------------------------------------------------------------- utilidades / CLI

def conectar(caminho):
    con = sqlite3.connect(caminho)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript((AQUI / "schema.sql").read_text(encoding="utf-8"))
    return con


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--banco", default=str(AQUI / "eleicoes2026.sqlite"))
    p.add_argument("--ano", type=int, default=ANO)
    p.add_argument("--dir-download", default=str(AQUI / "downloads"))
    p.add_argument("--manter-zip", action="store_true", help="não apaga os zips depois da carga")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("logs", help="baixa arquivos de urna e carrega os logs")
    s.add_argument("--turnos", type=int, nargs="+", default=[1, 2], choices=[1, 2])
    s.add_argument("--ufs", nargs="+", default=UFS, type=str.upper)
    s.add_argument("--processos", type=int, default=os.cpu_count())
    s.add_argument("--refazer", action="store_true")
    s.add_argument("--url-urna", default=URL_URNA)
    s.set_defaults(func=cmd_logs)

    s = sub.add_parser("votacao", help="baixa e carrega a votação por seção (Presidente)")
    s.add_argument("--url-votacao", default=URL_VOTACAO)
    s.set_defaults(func=cmd_votacao)

    s = sub.add_parser("analisar", help="gera o relatório de votos após as 17h")
    s.add_argument("--saida", default=str(AQUI / "resultados"))
    s.set_defaults(func=cmd_analisar)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
