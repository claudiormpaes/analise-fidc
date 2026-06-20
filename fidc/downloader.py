"""Download incremental dos informes mensais de FIDC do Portal de Dados Abertos CVM.

Estratégia:
- Arquivos anuais (HIST/) — ex.: inf_mensal_fidc_2013.zip — são estáticos;
  baixamos apenas uma vez (pulamos se o tamanho local já bate com o do servidor).
- Arquivos mensais (DADOS/) — ex.: inf_mensal_fidc_202601.zip — dos últimos
  ~13 meses são reprocessados semanalmente pela CVM (reenvios), então são
  sempre rebaixados. Os mais antigos seguem a regra de "pular se igual".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

import requests

import config


@dataclass
class RemoteFile:
    nome: str          # inf_mensal_fidc_202601.zip
    url: str           # URL completa
    competencia: str   # "AAAAMM" (mensal) ou "AAAA" (anual histórico)
    historico: bool    # True se veio da pasta HIST/ (arquivo anual)


def _listar_diretorio(url: str) -> list[str]:
    """Lê o índice HTML de um diretório do portal e devolve os nomes de .zip."""
    resp = config.SESSION.get(url, timeout=60)
    resp.raise_for_status()
    return sorted(set(re.findall(r"inf_mensal_fidc_\d{4,6}\.zip", resp.text)))


def descobrir_arquivos() -> list[RemoteFile]:
    """Descobre todos os ZIPs disponíveis (histórico anual + mensais)."""
    arquivos: list[RemoteFile] = []

    # Histórico anual (2013..2024 atualmente)
    for nome in _listar_diretorio(config.HIST_URL):
        comp = re.search(r"(\d{4,6})", nome).group(1)
        if len(comp) == 4 and int(comp) >= config.PRIMEIRO_ANO_HIST:
            arquivos.append(
                RemoteFile(nome, f"{config.HIST_URL}/{nome}", comp, historico=True)
            )

    # Mensais recentes (2025+)
    for nome in _listar_diretorio(config.BASE_URL):
        comp = re.search(r"(\d{4,6})", nome).group(1)
        if len(comp) == 6:
            arquivos.append(
                RemoteFile(nome, f"{config.BASE_URL}/{nome}", comp, historico=False)
            )

    return arquivos


def _tamanho_remoto(url: str) -> int | None:
    """Content-Length do arquivo remoto (None se o servidor não informar)."""
    try:
        resp = config.SESSION.head(url, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        tam = resp.headers.get("Content-Length")
        return int(tam) if tam is not None else None
    except requests.RequestException:
        return None


def _dentro_janela_refresh(competencia: str) -> bool:
    """True se a competência mensal está dentro da janela de reprocessamento."""
    if len(competencia) != 6:
        return False
    ano, mes = int(competencia[:4]), int(competencia[4:])
    hoje = date.today()
    meses_atras = (hoje.year - ano) * 12 + (hoje.month - mes)
    return 0 <= meses_atras <= config.JANELA_REFRESH_MESES


def _carregar_manifest() -> dict:
    if config.MANIFEST.exists():
        return json.loads(config.MANIFEST.read_text(encoding="utf-8"))
    return {}


def _salvar_manifest(manifest: dict) -> None:
    config.MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def baixar(rf: RemoteFile, manifest: dict, *, verbose: bool = True) -> bool:
    """Baixa um arquivo se necessário. Devolve True se houve (re)download."""
    destino = config.RAW_DIR / rf.nome
    info = manifest.get(rf.nome, {})

    # Mensais dentro da janela: sempre rebaixar (a CVM reprocessa reenvios).
    forcar = (not rf.historico) and _dentro_janela_refresh(rf.competencia)

    if destino.exists() and not forcar:
        tam_remoto = _tamanho_remoto(rf.url)
        if tam_remoto is not None and tam_remoto == destino.stat().st_size:
            if verbose:
                print(f"  [skip] {rf.nome} (inalterado)")
            return False

    if verbose:
        print(f"  [get ] {rf.nome}")
    resp = config.SESSION.get(rf.url, timeout=300, stream=True)
    resp.raise_for_status()
    tmp = destino.with_suffix(".zip.part")
    with open(tmp, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            fh.write(chunk)
    tmp.replace(destino)

    manifest[rf.nome] = {"size": destino.stat().st_size, "competencia": rf.competencia,
                         "historico": rf.historico}
    return True


def sincronizar(*, verbose: bool = True) -> list[str]:
    """Baixa tudo o que falta/mudou. Devolve a lista de arquivos (re)baixados."""
    config.ensure_dirs()
    manifest = _carregar_manifest()
    arquivos = descobrir_arquivos()
    if verbose:
        print(f"Descobertos {len(arquivos)} arquivos no portal CVM.")

    baixados: list[str] = []
    for rf in arquivos:
        try:
            if baixar(rf, manifest, verbose=verbose):
                baixados.append(rf.nome)
        except requests.RequestException as exc:
            print(f"  [erro] {rf.nome}: {exc}")
    _salvar_manifest(manifest)
    return baixados


if __name__ == "__main__":
    novos = sincronizar()
    print(f"\n{len(novos)} arquivo(s) baixado(s)/atualizado(s).")
