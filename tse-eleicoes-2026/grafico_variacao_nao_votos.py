"""Gráfico (HTML) da variação de abstenções, brancos e nulos do 1º para o 2º turno nas presidenciais recentes.

    python3 grafico_variacao_nao_votos.py serie_historica.csv saida.html [--desde 2016]
Lê a série gerada por serie_historica.py. Todos os percentuais são sobre os eleitores aptos.
"""
import argparse, csv
from pathlib import Path


def p(x, d=1, sinal=False):
    if round(x, d) == 0:
        x = 0.0
    return (f"{x:+.{d}f}" if sinal else f"{x:.{d}f}").replace(".", ",")


def mi(x): return f"{x/1e6:.2f}".replace(".", ",")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serie"); ap.add_argument("saida"); ap.add_argument("--desde", type=int, default=2016)
    a = ap.parse_args()
    h = {}
    with open(a.serie, newline="") as f:
        for r in csv.DictReader(f):
            h.setdefault(int(r["ano"]), {})[int(r["turno"])] = {k: int(r[k]) for k in ("aptos", "abstencoes", "brancos", "nulos")}
    anos = [y for y in sorted(h) if len(h[y]) == 2 and y >= a.desde]

    def val(y, t, k):
        x = h[y][t]; ap_ = x["aptos"]
        n = {"nv": x["abstencoes"] + x["brancos"] + x["nulos"], "ab": x["abstencoes"], "br": x["brancos"], "nu": x["nulos"]}[k]
        return 100 * n / ap_, n

    PAIN = [("nv", "Abstenção + brancos + nulos", "X", 0, 32, 8), ("ab", "Abstenção", "A", 0, 25, 5), ("br", "Brancos", "B", 0, 3, 1), ("nu", "Nulos", "N", 0, 6, 2)]
    W, H, mt, mb = 1000, 330, 56, 40
    pw, gap, x0 = 192, 52, 40
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Variação de abstenção, brancos e nulos do 1º para o 2º turno em cada eleição presidencial">']
    for k, (key, titulo, cls, lo, hi, tk) in enumerate(PAIN):
        px = x0 + k * (pw + gap)
        Y = lambda v, lo=lo, hi=hi: mt + (H - mt - mb) * (1 - (v - lo) / (hi - lo))
        s.append(f'<text x="{px}" y="20" class="ptit">{titulo}</text><text x="{px}" y="36" class="eixo">% dos eleitores aptos</text>')
        for v in range(lo, hi + 1, tk):
            s.append(f'<line x1="{px}" x2="{px+pw}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grade"/><text x="{px-6}" y="{Y(v)+4:.1f}" class="eixo" text-anchor="end">{v}%</text>')
        gw = pw / len(anos)
        for i, y in enumerate(anos):
            (v1, n1), (v2, n2) = val(y, 1, key), val(y, 2, key)
            gx = px + gw * i + gw * 0.12; bw = gw * 0.36
            for j, (v, n, t) in enumerate(((v1, n1, 1), (v2, n2, 2))):
                bx = gx + j * (bw + 3)
                s.append(f'<rect x="{bx:.1f}" y="{Y(v):.1f}" width="{bw:.1f}" height="{Y(0)-Y(v):.1f}" rx="2" class="barra {cls} t{t}"><title>{y}, {t}º turno: {p(v,2)}% dos aptos ({n:,} eleitores)</title></rect>'.replace(",", "."))
                s.append(f'<text x="{bx+bw/2:.1f}" y="{Y(v)-5:.1f}" class="val" text-anchor="middle">{p(v,1)}</text>')
            d = v2 - v1
            s.append(f'<text x="{gx+bw+1.5:.1f}" y="{H-mb+34}" class="delta {"neg" if d < 0 else "pos"}" text-anchor="middle">{p(d,2,True)}</text>')
            s.append(f'<text x="{gx+bw+1.5:.1f}" y="{H-mb+16}" class="ano" text-anchor="middle">{y}</text>')
    s.append("</svg>")
    svg = "\n".join(s)

    linhas = ""
    for y in anos:
        for k, nome, _, _, _, _ in PAIN:
            (v1, n1), (v2, n2) = val(y, 1, k), val(y, 2, k)
            linhas += (f'<tr><td>{y}</td><td>{nome}</td><td>{mi(n1)} mi</td><td>{mi(n2)} mi</td><td>{p(v1,2)}%</td><td>{p(v2,2)}%</td>'
                       f'<td class="{"neg" if v2<v1 else "pos"}"><b>{p(v2-v1,2,True)} p.p.</b></td><td class="{"neg" if v2<v1 else "pos"}">{p(100*(v2/v1-1),1,True)}%</td></tr>')

    html = f'''<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Variação de abstenções, brancos e nulos — Presidente {anos[0]}–{anos[-1]}</title>
<style>
/* Layout: gráfico de colunas pareadas (1º e 2º turno) em quatro painéis, tabela com os valores embaixo. */
:root {{ --bg:#eef1f5; --papel:#fff; --tinta:#16202e; --suave:#5a6677; --linha:#d9dfe8; --faixa:#f6f8fb;
  --X:#16202e; --A:#b7791f; --B:#0f8a7a; --N:#7a52b3; --neg:#0f8a7a; --pos:#b7791f;
  --serif: Charter,"Iowan Old Style","Palatino Linotype",Georgia,serif; --sans: system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0b1017; --papel:#171f2b; --tinta:#e8edf4; --suave:#9aa6b8; --linha:#2a3545; --faixa:#1b2433;
  --X:#e8edf4; --A:#f0b84a; --B:#43c9b6; --N:#b79cf0; --neg:#43c9b6; --pos:#f0b84a; color-scheme: dark; }} }}
:root[data-theme="dark"] {{ --bg:#0b1017; --papel:#171f2b; --tinta:#e8edf4; --suave:#9aa6b8; --linha:#2a3545; --faixa:#1b2433;
  --X:#e8edf4; --A:#f0b84a; --B:#43c9b6; --N:#b79cf0; --neg:#43c9b6; --pos:#f0b84a; color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--tinta); font:14px/1.5 var(--sans); padding:24px max(16px, env(safe-area-inset-right,0px)) 24px max(16px, env(safe-area-inset-left,0px)); }}
main {{ max-width:1040px; margin:0 auto; background:var(--papel); border:1px solid var(--linha); border-radius:12px; padding:24px 26px; display:grid; grid-template-columns:minmax(0,1fr); gap:16px; min-width:0; }}
h1 {{ font:700 24px/1.25 var(--serif); margin:0; text-wrap:balance; }} h3 {{ font:600 11.5px/1.3 var(--sans); text-transform:uppercase; letter-spacing:.08em; color:var(--suave); margin:0 0 6px; }}
.sub {{ color:var(--suave); font-size:13px; }} .leg {{ color:var(--suave); font-size:12.5px; max-width:95ch; margin:0; }}
.cab {{ border-bottom:2px solid var(--tinta); padding-bottom:8px; display:grid; gap:2px; }}
.graf {{ overflow-x:auto; }} .graf svg {{ min-width:760px; width:100%; height:auto; display:block; }}
svg text {{ font-family:var(--sans); fill:var(--suave); }} .ptit {{ font-size:13.5px; font-weight:700; fill:var(--tinta); }} .eixo {{ font-size:11px; font-variant-numeric:tabular-nums; }}
.grade {{ stroke:var(--linha); stroke-width:1; }} svg .val {{ font-size:11px; font-weight:700; fill:var(--tinta); font-variant-numeric:tabular-nums; }} svg .ano {{ font-size:12.5px; font-weight:700; fill:var(--tinta); }}
svg .delta {{ font-size:12px; font-weight:700; font-variant-numeric:tabular-nums; }} svg .delta.neg {{ fill:var(--neg); }} svg .delta.pos {{ fill:var(--pos); }}
.barra.X {{ fill:var(--X); }} .barra.A {{ fill:var(--A); }} .barra.B {{ fill:var(--B); }} .barra.N {{ fill:var(--N); }} .barra.t1 {{ opacity:.38; }}
.leg2 {{ display:flex; gap:16px; flex-wrap:wrap; font-size:12px; color:var(--suave); }} .leg2 span {{ display:inline-flex; align-items:center; gap:6px; }}
.leg2 i {{ display:inline-block; width:12px; height:12px; border-radius:2px; background:var(--tinta); }} .leg2 i.c1 {{ opacity:.38; }}
.tab {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; font-size:12.5px; font-variant-numeric:tabular-nums; }}
th,td {{ padding:4px 8px; text-align:right; border-bottom:1px solid var(--linha); white-space:nowrap; }} th:nth-child(2),td:nth-child(2) {{ text-align:left; }} th:first-child,td:first-child {{ text-align:left; font-weight:600; }}
thead th {{ font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--suave); font-weight:600; }} tbody tr:nth-child(8n+1) td, tbody tr:nth-child(8n+2) td,tbody tr:nth-child(8n+3) td,tbody tr:nth-child(8n+4) td {{ background:var(--faixa); }}
td.neg {{ color:var(--neg); }} td.pos {{ color:var(--pos); }}
</style>
</head>
<body>
<main>
  <div class="cab"><h1>Abstenções, brancos e nulos: variação do 1º para o 2º turno</h1>
  <div class="sub">Eleições presidenciais {", ".join(str(y) for y in anos)} · % dos eleitores aptos · dados abertos do TSE</div></div>
  <div class="graf">{svg}</div>
  <div class="leg2"><span><i class="c1"></i>1º turno</span><span><i></i>2º turno</span><span style="color:var(--neg)">&#9632; redução entre os turnos</span><span style="color:var(--pos)">&#9632; aumento entre os turnos</span></div>
  <div><h3>Valores</h3><div class="tab"><table>
    <thead><tr><th>Ano</th><th>Medida</th><th>1º turno</th><th>2º turno</th><th>1º (% aptos)</th><th>2º (% aptos)</th><th>Variação</th><th>Variação relativa</th></tr></thead>
    <tbody>{linhas}</tbody></table></div></div>
  <p class="leg">Janela de 10 anos (de {a.desde} a 2026): as três eleições presidenciais do período, todas com 2º turno. Abstenção = aptos menos comparecidos. Os aptos de 2026 vêm do perfil do eleitorado de julho de 2026; os de 2018 e 2022 vêm do TSE no dia da eleição. Para uma janela maior, use <code>--desde 2002</code>.</p>
</main>
</body>
</html>
'''
    Path(a.saida).write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
