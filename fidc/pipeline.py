"""Orquestrador: baixa da CVM e reconsolida a base. Rodar diariamente."""
from __future__ import annotations

import time

from fidc import benchmarks, carteira, cedentes_nomes, downloader, processor


def run(*, verbose: bool = True) -> None:
    inicio = time.time()
    if verbose:
        print("=" * 60)
        print("PIPELINE FIDC — sincronizando com o Portal de Dados Abertos CVM")
        print("=" * 60)

    # Informe Mensal de FIDC
    baixados = downloader.sincronizar(verbose=verbose)
    if verbose:
        print(f"\n{len(baixados)} arquivo(s) novo(s)/atualizado(s).\n")

    processor.consolidar(verbose=verbose)

    # Benchmarks (best-effort — não derruba o pipeline se APIs estiverem fora)
    for nome, fn in [("CDI", benchmarks.fetch_cdi),
                     ("IPCA", benchmarks.fetch_ipca),
                     ("SELIC", benchmarks.fetch_selic)]:
        try:
            fn(verbose=verbose)
        except Exception as exc:  # noqa: BLE001
            print(f"  [aviso] {nome} não atualizado: {exc}")

    # CDA — Composição de carteira (best-effort)
    try:
        carteira.sincronizar(verbose=verbose)
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] CDA carteira não atualizado: {exc}")

    # Razão social dos maiores cedentes via BrasilAPI (best-effort, incremental)
    try:
        cedentes_nomes.enriquecer(verbose=verbose)
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] nomes de cedentes não enriquecidos: {exc}")

    if verbose:
        print(f"\nConcluído em {time.time() - inicio:.1f}s.")


if __name__ == "__main__":
    run()
