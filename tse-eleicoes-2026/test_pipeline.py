"""Teste ponta a ponta com arquivos sintéticos no formato do TSE (não usa dados reais).

    python -m unittest test_pipeline.py
"""

import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import py7zr

AQUI = Path(__file__).resolve().parent


def linha_log(data, hora, msg):
    return f"{data} {hora}\tINFO\t67305985\tVOTA\t{msg}\t0123456789ABCDEF\n"


def logjez(horas_votos, data="04/10/2026"):
    texto = linha_log("28/09/2026", "10:00:00", "O voto do eleitor foi computado")  # carga: ignorar
    texto += linha_log(data, "07:30:00", "Urna pronta para receber votos")
    for h in horas_votos:
        texto += linha_log(data, h, "Eleitor foi habilitado")
        texto += linha_log(data, h, "O voto do eleitor foi computado")
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w") as z:
        z.writestr(texto.encode("latin-1"), "logd.dat")
    return buf.getvalue()


class TestPipeline(unittest.TestCase):
    def test_ponta_a_ponta(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # AC: relógio das urnas 2h atrás de Brasília; 15:10 local = 17:10 Brasília.
            ac = ["06:00:30", "09:00:00", "14:59:59", "15:10:00", "15:20:00"]
            # SP: relógio = Brasília; 17:05 é após o encerramento.
            sp = ["08:00:15", "12:00:00", "16:59:59", "17:05:00"]
            for uf, mun, horas in [("AC", "01120", ac), ("SP", "71072", sp)]:
                with zipfile.ZipFile(tmp / f"bu_imgbu_logjez_rdv_vscmr_2026_1t_{uf}.zip", "w") as zf:
                    for secao in range(1, 7):
                        zf.writestr(f"o00406-{mun}0001{secao:04d}.logjez", logjez(horas))
                        zf.writestr(f"o00406-{mun}0001{secao:04d}.bu", b"ignorar")

            cab = "NR_TURNO;SG_UF;CD_MUNICIPIO;NM_MUNICIPIO;NR_ZONA;NR_SECAO;CD_CARGO;NR_VOTAVEL;" \
                  "NM_VOTAVEL;QT_VOTOS;QT_APTOS;QT_COMPARECIMENTO;QT_ABSTENCOES\n"
            linhas = [f'"1";"AC";"1120";"RIO BRANCO";"1";"{s}";"1";"99";"X";"5";"10";"5";"5"\n'
                      for s in range(1, 7)]
            linhas += [f'"1";"SP";"71072";"SAO PAULO";"1";"{s}";"1";"99";"X";"4";"10";"4";"6"\n'
                       for s in range(1, 7)]
            with zipfile.ZipFile(tmp / "votacao_secao_2026_BR.zip", "w") as zf:
                zf.writestr("votacao_secao_2026_BR.csv", (cab + "".join(linhas)).encode("latin-1"))

            banco = tmp / "teste.sqlite"
            base = [sys.executable, str(AQUI / "tse.py"), "--banco", str(banco),
                    "--dir-download", str(tmp / "dl")]
            url_urna = (tmp.as_uri() + "/bu_imgbu_logjez_rdv_vscmr_{ano}_{turno}t_{uf}.zip")
            subprocess.run(base + ["logs", "--turnos", "1", "--ufs", "AC", "SP", "--processos", "2",
                                   "--url-urna", url_urna], check=True)
            subprocess.run(base + ["votacao", "--url-votacao",
                                   tmp.as_uri() + "/votacao_secao_{ano}_BR.zip"], check=True)
            subprocess.run(base + ["analisar", "--saida", str(tmp / "res")], check=True)

            con = sqlite3.connect(banco)
            self.assertEqual(dict(con.execute("SELECT uf, offset_h FROM fuso_municipio")), {"AC": 2, "SP": 0})
            resumo = (tmp / "res" / "resumo_turno.csv").read_text().splitlines()
            # 6 seções x (5 votos AC + 4 votos SP) = 54; após 17h: 6x2 (AC) + 6x1 (SP) = 18
            self.assertEqual(resumo[1].split(",")[:3], ["1", "54", "18"])
            conf = (tmp / "res" / "conferencia_comparecimento.csv").read_text().splitlines()
            self.assertEqual(conf[1], "1,12,12,54,54,0")


if __name__ == "__main__":
    unittest.main()
