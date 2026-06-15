"""Orquestrador: baixa da CVM e reconsolida a base. Rodar diariamente."""
from __future__ import annotations

import time

from fidc import benchmarks, downloader, processor


def run(*, verbose: bool = True) -> None:
    inicio = time.time()
    if verbose:
        print("=" * 60)
        print("PIPELINE FIDC — sincronizando com o Portal de Dados Abertos CVM")
        print("=" * 60)

    baixados = downloader.sincronizar(verbose=verbose)
    if verbose:
        print(f"\n{len(baixados)} arquivo(s) novo(s)/atualizado(s).\n")

    processor.consolidar(verbose=verbose)

    # Benchmark CDI (best-effort: não derruba o pipeline se a API estiver fora)
    try:
        benchmarks.fetch_cdi(verbose=verbose)
    except Exception as exc:  # noqa: BLE001
        print(f"  [aviso] CDI não atualizado: {exc}")

    if verbose:
        print(f"\nConcluído em {time.time() - inicio:.1f}s.")


if __name__ == "__main__":
    run()
