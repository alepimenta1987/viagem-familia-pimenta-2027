"""Série histórica de abstenções, brancos e nulos nas eleições presidenciais (1º e 2º turno).

2002-2022: arquivos "detalhe_votacao_munzona" do TSE (cargo 1, soma do país, inclusive exterior).
2026: votação por seção carregada em eleicoes2026.sqlite, com os aptos do perfil do eleitorado.

    python3 serie_historica.py serie_historica.csv --perfil-zip perfil_eleitorado_2026.zip
"""
import argparse, csv, io, os, sqlite3, urllib.request, zipfile

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_{ano}.zip"
ANOS = (1994, 1998, 2002, 2006, 2010, 2014, 2018, 2022)


def historico(ano, cache):
    caminho = os.path.join(cache, f"detalhe_votacao_munzona_{ano}.zip")
    if not os.path.exists(caminho):
        os.makedirs(cache, exist_ok=True)
        urllib.request.urlretrieve(URL.format(ano=ano), caminho)
    soma = {}
    with zipfile.ZipFile(caminho) as z:
        nome = next(n for n in z.namelist() if n.endswith("BRASIL.csv"))
        with z.open(nome) as f:
            for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"):
                if r["CD_CARGO"] != "1":
                    continue
                a = soma.setdefault(int(r["NR_TURNO"]), [0, 0, 0, 0])
                a[0] += int(r["QT_APTOS"]); a[1] += int(r["QT_ABSTENCOES"])
                a[2] += int(r["QT_VOTOS_BRANCOS"]); a[3] += int(r["QT_VOTOS_NULOS"])
    return soma


def aptos_2026(caminho_zip):
    total = 0
    with zipfile.ZipFile(caminho_zip) as z:
        for nome in z.namelist():
            if nome.endswith(".csv") and "BRASIL" not in nome:
                with z.open(nome) as f:
                    total += sum(int(r["QT_ELEITORES"]) for r in
                                 csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"))
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("saida"); ap.add_argument("--perfil-zip"); ap.add_argument("--banco", default="eleicoes2026.sqlite")
    ap.add_argument("--cache", default="downloads/historico")
    a = ap.parse_args()
    linhas = []
    for ano in ANOS:
        for turno, (aptos, abst, bran, nul) in sorted(historico(ano, a.cache).items()):
            linhas.append((ano, turno, aptos, abst, bran, nul))
    if a.perfil_zip:
        aptos = aptos_2026(a.perfil_zip)
        con = sqlite3.connect(a.banco)
        for turno in (1, 2):
            comp, bran, nul = con.execute(
                "SELECT SUM(qt_votos), SUM(CASE WHEN nr_votavel = 95 THEN qt_votos END), "
                "SUM(CASE WHEN nr_votavel = 96 THEN qt_votos END) FROM votacao_secao WHERE turno = ?", (turno,)).fetchone()
            linhas.append((2026, turno, aptos, aptos - comp, bran, nul))
    with open(a.saida, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ano", "turno", "aptos", "abstencoes", "brancos", "nulos"])
        w.writerows(linhas)


if __name__ == "__main__":
    main()
