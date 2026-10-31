"""Estimativa de transferência de votos entre o 1º e o 2º turno (inferência ecológica).

Origens (1º turno): Lula, Flávio, Outros+Brancos+Nulos, Abstenção.
Destinos (2º turno): Lula, Flávio, Branco/Nulo, Abstenção.
Para cada UF, ajusta por mínimos quadrados ponderados pelo eleitorado uma matriz de transição
com linhas positivas somando 1, usando as participações de cada município (fração do eleitorado).
Intervalos de 95% por bootstrap de municípios dentro de cada UF.

    python3 modelo_transferencias.py perfil_eleitorado_2026.zip saida.json [--boot 300]
Requer numpy e o banco eleicoes2026.sqlite (votacao_secao carregada por tse.py).
"""
import argparse, csv, io, json, sqlite3, zipfile
import numpy as np

LULA, FLAVIO, BRANCO, NULO = 13, 22, 95, 96


def eleitorado_por_municipio(caminho_zip):
    el = {}
    with zipfile.ZipFile(caminho_zip) as z:
        for nome in z.namelist():
            if not nome.endswith(".csv") or "BRASIL" in nome:
                continue
            with z.open(nome) as f:
                for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"):
                    k = (r["SG_UF"], int(r["CD_MUNICIPIO"]))
                    el[k] = el.get(k, 0) + int(r["QT_ELEITORES"])
    return el


def tabela_municipios(banco, el):
    con = sqlite3.connect(banco)
    d = {}
    for uf, mun, turno, votavel, q in con.execute(
            "SELECT uf, cd_municipio, turno, nr_votavel, SUM(qt_votos) FROM votacao_secao GROUP BY 1, 2, 3, 4"):
        x = d.setdefault((uf, mun), {})
        cat = {LULA: "L", FLAVIO: "F", BRANCO: "B", NULO: "B"}.get(votavel, "O")
        x[cat + str(turno)] = x.get(cat + str(turno), 0) + q
    chaves = [k for k in d if k in el]
    ufs = np.array([k[0] for k in chaves])
    e = np.array([el[k] for k in chaves], float)
    c = lambda cat, t: np.array([d[k].get(cat + t, 0) for k in chaves], float)
    t1 = sum(c(cat, "1") for cat in "LFOB"); t2 = sum(c(cat, "2") for cat in "LFOB")
    X = np.column_stack([c("L", "1"), c("F", "1"), c("O", "1") + c("B", "1"), e - t1]) / e[:, None]
    Y = np.column_stack([c("L", "2"), c("F", "2"), c("B", "2"), e - t2]) / e[:, None]
    return ufs, e, X, Y


def projeta_simplex(V):
    U = np.sort(V, axis=1)[:, ::-1]
    css = np.cumsum(U, axis=1) - 1
    k = np.arange(1, V.shape[1] + 1)
    rho = (U - css / k > 0).sum(axis=1)
    return np.maximum(V - (css[np.arange(len(V)), rho - 1] / rho)[:, None], 0)


def ajusta(X, Y, w, iteracoes=3000):
    """Gradiente projetado acelerado (FISTA) para min sum_i w_i ||y_i - x_i P||^2, P com linhas no simplex."""
    A = (X * w[:, None]).T @ X
    B = (X * w[:, None]).T @ Y
    L = np.linalg.eigvalsh(A).max() * 2
    P = np.full((X.shape[1], Y.shape[1]), 1 / Y.shape[1]); Z = P.copy(); t = 1
    for _ in range(iteracoes):
        Pn = projeta_simplex(Z - 2 * (A @ Z - B) / L)
        tn = (1 + np.sqrt(1 + 4 * t * t)) / 2
        Z = Pn + (t - 1) / tn * (Pn - P); P, t = Pn, tn
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("perfil_zip"); ap.add_argument("saida")
    ap.add_argument("--banco", default="eleicoes2026.sqlite"); ap.add_argument("--boot", type=int, default=300)
    a = ap.parse_args()
    ufs, e, X, Y = tabela_municipios(a.banco, eleitorado_por_municipio(a.perfil_zip))
    idx = {u: np.where(ufs == u)[0] for u in sorted(set(ufs))}
    tot_uf = {u: (X[i] * e[i][:, None]).sum(0) for u, i in idx.items()}
    peso = lambda i: e[i] / e[i].sum()

    F = sum(ajusta(X[i], Y[i], peso(i)) * tot_uf[u][:, None] for u, i in idx.items())
    Fnac = ajusta(X, Y, e / e.sum()) * (X * e[:, None]).sum(0)[:, None]
    rng = np.random.default_rng(2026)
    Fb = []
    for _ in range(a.boot):
        Fb.append(sum(ajusta(X[s], Y[s], peso(s), 1200) * tot_uf[u][:, None]
                      for u, i in idx.items() for s in [i[rng.integers(0, len(i), len(i))]]))
    Fb = np.array(Fb)
    Yh = np.zeros_like(Y)
    for u, i in idx.items():
        Yh[i] = X[i] @ ajusta(X[i], Y[i], peso(i))
    w = e / e.sum()
    r2 = 1 - (w[:, None] * (Y - Yh) ** 2).sum() / (w[:, None] * (Y - (w[:, None] * Y).sum(0)) ** 2).sum()
    json.dump(dict(F=F.tolist(), lo=np.percentile(Fb, 2.5, axis=0).tolist(), hi=np.percentile(Fb, 97.5, axis=0).tolist(),
                   Fnac=Fnac.tolist(), tot1=(X * e[:, None]).sum(0).tolist(), tot2=(Y * e[:, None]).sum(0).tolist(),
                   r2=float(r2), n=int(len(e)), boot=a.boot, ufs=len(idx)), open(a.saida, "w"))


if __name__ == "__main__":
    main()
