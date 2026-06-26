"""Assa os parquets do HF Dataset dentro da imagem Docker (build time).

Elimina o download lento/rate-limited a cada cold start no Cloud Run. Tolera
arquivo ainda não publicado: o app cai no download em runtime (_garantir_dados_hf).
Roda no build (ver Dockerfile). Mantido como script (e não heredoc no Dockerfile)
porque o builder clássico do Cloud Build não suporta heredoc em instruções RUN.
"""
import os
import shutil

from huggingface_hub import hf_hub_download

REPO = "claudiormpaes/fidc-dados"
ARQUIVOS = [
    "fidc_consolidado.parquet",
    "fidc_cotas.parquet",
    "fidc_cedentes.parquet",
    "cedentes_nomes.parquet",
    "fidc_carteira.parquet",
    "cdi_mensal.parquet",
    "ipca_mensal.parquet",
    "selic_mensal.parquet",
]


def main() -> None:
    os.makedirs("data/processed", exist_ok=True)
    for f in ARQUIVOS:
        try:
            origem = hf_hub_download(repo_id=REPO, filename=f, repo_type="dataset")
            shutil.copy(origem, os.path.join("data/processed", f))
            print("baked", f)
        except Exception as e:  # noqa: BLE001 — arquivo ausente não quebra o build
            print("skip", f, "->", e)


if __name__ == "__main__":
    main()
