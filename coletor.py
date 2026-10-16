#!/usr/bin/env python3
"""
Coleta diária das notícias de esporte das prefeituras da Grande Vitória
e gera a página docs/index.html.

Regras de boa conduta embutidas:
- lê o robots.txt de cada site antes de acessar; se não permitir, não acessa;
- se um site bloquear (403, 429, bot detection), não tenta contornar;
- identifica-se com um User-Agent honesto e espera entre as requisições.

Uso:  python coletor.py
"""
import html
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
DOCS_DIR = BASE / "docs"
ARQ_ITENS = DATA_DIR / "itens.json"
ARQ_HTML = DOCS_DIR / "index.html"

UA = "NoticiasEsporteGV/1.0 (leitura pessoal de noticias publicas)"
TZ = timezone(timedelta(hours=-3))  # horário de Brasília
DIAS_GUARDADOS = 45
PAUSA_ENTRE_SITES = 3  # segundos

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})

# --------------------------------------------------------------------------
# CONFIGURAÇÃO DAS PREFEITURAS
#
# estrategia:
#   "secretaria"  -> a página já é só da Secretaria de Esportes (sem filtro)
#   "generico"    -> página de notícias geral; filtra por palavras-chave
#
# Para ajustar um site, mude a "url" (página de listagem de notícias).
# --------------------------------------------------------------------------
CIDADES = [
    {
        "nome": "Vitória",
        "url": "https://www.vitoria.es.gov.br/imprensa/todas_noticias/semesp",
        "estrategia": "secretaria",
        "parser": "vitoria",
    },
    {"nome": "Vila Velha", "url": "https://www.vilavelha.es.gov.br/noticias",
     "estrategia": "generico", "parser": "generico"},
    {"nome": "Serra", "url": "https://www.serra.es.gov.br/noticias/",
     "estrategia": "generico", "parser": "generico"},
    {"nome": "Cariacica", "url": "https://www.cariacica.es.gov.br/noticias",
     "estrategia": "generico", "parser": "generico"},
    {"nome": "Viana", "url": "https://www.viana.es.gov.br/noticias",
     "estrategia": "generico", "parser": "generico"},
    {"nome": "Guarapari", "url": "https://www.guarapari.es.gov.br/noticias",
     "estrategia": "generico", "parser": "generico"},
    {"nome": "Fundão", "url": "https://www.fundao.es.gov.br/noticias",
     "estrategia": "generico", "parser": "generico"},
]

PALAVRAS_CHAVE = [
    "esporte", "esportes", "esportivo", "esportiva", "semesp", "semel",
    "lazer", "futebol", "futsal", "society", "campeonato", "torneio",
    "copa ", "atleta", "atletismo", "olimpiada", "jogos escolares",
    "jogos municipais", "volei", "basquete", "handebol", "natacao",
    "hidroginastica", "judo", "karate", "jiu-jitsu", "capoeira", "skate",
    "surf", "bodyboard", "beach tennis", "tenis", "maratona", "corrida",
    "meia maratona", "ciclismo", "paradesporto", "bolsa atleta",
    "escolinha", "nucleo esportivo", "nucleos esportivos", "ginastica",
    "arena", "ginasio", "quadra", "vela ", "remo", "bocha",
]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt).lower()


def eh_esporte(texto: str) -> bool:
    t = " " + normalizar(texto) + " "
    for kw in PALAVRAS_CHAVE:
        if re.search(r"(?<![a-z])" + re.escape(kw), t):
            return True
    return False


def agora() -> datetime:
    return datetime.now(TZ)


# --------------------------------------------------------------------------
# Acesso educado aos sites
# --------------------------------------------------------------------------
class Bloqueado(Exception):
    """O site não permite (ou bloqueou) o acesso automático."""


class Falha(Exception):
    """Erro técnico ao acessar o site."""


def checar_robots(url: str) -> None:
    p = urlparse(url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        r = SESSION.get(robots_url, timeout=20)
    except requests.RequestException as e:
        raise Falha(f"não consegui verificar o robots.txt ({type(e).__name__})")
    if r.status_code in (401, 403, 429):
        raise Bloqueado("o site bloqueia acesso automático (robots.txt inacessível)")
    if r.status_code >= 500:
        raise Falha(f"servidor com erro ao ler robots.txt (HTTP {r.status_code})")
    if r.status_code == 404:
        return  # sem robots.txt: sem restrições declaradas
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    if not rp.can_fetch(UA, url):
        raise Bloqueado("o robots.txt do site não permite acesso automático")


def baixar(url: str) -> BeautifulSoup:
    checar_robots(url)
    try:
        r = SESSION.get(url, timeout=30)
    except requests.RequestException as e:
        raise Falha(f"falha de conexão ({type(e).__name__})")
    if r.status_code in (401, 403, 429):
        raise Bloqueado(f"o site recusou o acesso (HTTP {r.status_code})")
    if r.status_code >= 400:
        raise Falha(f"o site respondeu HTTP {r.status_code}")
    return BeautifulSoup(r.content, "html.parser")


# --------------------------------------------------------------------------
# Parsers de cada tipo de site
# --------------------------------------------------------------------------
def _data_dd_mm(texto: str, hoje: date):
    m = re.match(r"^\s*(\d{2})/(\d{2})\s*$", texto)
    if not m:
        return None
    dia, mes = int(m.group(1)), int(m.group(2))
    for ano in (hoje.year, hoje.year - 1):
        try:
            d = date(ano, mes, dia)
        except ValueError:
            return None
        if d <= hoje:
            return d
    return None


def parse_vitoria(soup: BeautifulSoup, url_base: str) -> list[dict]:
    """Listagem de notícias do portal de Vitória (datas dd/mm antes dos links)."""
    hoje = agora().date()
    itens, vistos = [], set()
    for a in soup.find_all("a", href=re.compile(r"/noticia/")):
        titulo = a.get_text(" ", strip=True)
        link = urljoin(url_base, a["href"])
        if not titulo or link in vistos:
            continue
        vistos.add(link)
        marcador = a.find_previous(string=re.compile(r"^\s*\d{2}/\d{2}\s*$"))
        data = _data_dd_mm(marcador, hoje) if marcador else None
        itens.append({"titulo": titulo, "url": link,
                      "data": data.isoformat() if data else None})
    return itens


def parse_generico(soup: BeautifulSoup, url_base: str) -> list[dict]:
    """Parser genérico: links longos que apontam para notícias do mesmo site."""
    host = urlparse(url_base).netloc.removeprefix("www.")
    itens, vistos = [], set()
    for a in soup.find_all("a", href=True):
        titulo = a.get_text(" ", strip=True)
        if len(titulo) < 25:
            continue
        link = urljoin(url_base, a["href"])
        pu = urlparse(link)
        if pu.netloc.removeprefix("www.") != host:
            continue
        if "notic" not in pu.path.lower() or pu.path.rstrip("/") == urlparse(url_base).path.rstrip("/"):
            continue
        if link in vistos:
            continue
        vistos.add(link)
        # contexto: texto do "card" que envolve o link (para achar data e palavras-chave).
        # Sobe até 3 níveis, mas para antes de englobar outras notícias.
        bloco = a
        for _ in range(3):
            pai = bloco.parent
            if pai is None:
                break
            outros = [x for x in pai.find_all("a", href=True)
                      if "notic" in x["href"].lower()
                      and len(x.get_text(" ", strip=True)) >= 25]
            if len(outros) > 1:
                break
            bloco = pai
        contexto = bloco.get_text(" ", strip=True)[:400]
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", contexto)
        data = None
        if m:
            try:
                data = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                pass
        itens.append({"titulo": titulo, "url": link, "data": data, "_contexto": contexto})
    return itens


PARSERS = {"vitoria": parse_vitoria, "generico": parse_generico}


# --------------------------------------------------------------------------
# Coleta
# --------------------------------------------------------------------------
def coletar_cidade(cfg: dict) -> tuple[list[dict], dict]:
    soup = baixar(cfg["url"])
    brutos = PARSERS[cfg["parser"]](soup, cfg["url"])
    if cfg["estrategia"] == "secretaria":
        esportes = brutos
    else:
        esportes = [i for i in brutos if eh_esporte(i["titulo"] + " " + i.get("_contexto", ""))]
    for i in esportes:
        i.pop("_contexto", None)
        i["cidade"] = cfg["nome"]
    status = {
        "estado": "ok",
        "mensagem": f"{len(brutos)} notícias lidas, {len(esportes)} de esporte",
    }
    if not brutos:
        status = {"estado": "aviso",
                  "mensagem": "página lida, mas nenhuma notícia reconhecida (o layout pode ter mudado)"}
    return esportes, status


def carregar_itens() -> dict:
    if ARQ_ITENS.exists():
        return json.loads(ARQ_ITENS.read_text(encoding="utf-8"))
    return {}


def salvar_itens(itens: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    ARQ_ITENS.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# Página HTML
# --------------------------------------------------------------------------
def fmt_data(iso):
    if not iso:
        return "sem data"
    d = date.fromisoformat(iso)
    return d.strftime("%d/%m/%Y")


def _lista(itens: list[dict], hoje_iso: str) -> str:
    por_cidade: dict[str, list[dict]] = {}
    for i in itens:
        por_cidade.setdefault(i["cidade"], []).append(i)
    partes = []
    ordem = [c["nome"] for c in CIDADES]
    for cidade in sorted(por_cidade, key=lambda c: ordem.index(c) if c in ordem else 99):
        lis = []
        for i in sorted(por_cidade[cidade], key=lambda x: (x.get("data") or "", x["visto_em"]), reverse=True):
            novo = '<span class="novo">novo</span>' if i["visto_em"] == hoje_iso else ""
            lis.append(
                f'<li><a href="{html.escape(i["url"])}" target="_blank" rel="noopener">'
                f'{html.escape(i["titulo"])}</a> {novo}'
                f'<span class="data">{fmt_data(i.get("data"))}</span></li>'
            )
        partes.append(f"<h3>{html.escape(cidade)}</h3><ul>{''.join(lis)}</ul>")
    return "".join(partes)


def gerar_html(itens: dict, status_cidades: list[dict], primeira_execucao: bool) -> str:
    agora_dt = agora()
    hoje_iso = agora_dt.date().isoformat()
    lista = [{"url": u, **v} for u, v in itens.items()]
    novos = [i for i in lista if i["visto_em"] == hoje_iso]
    antigos = [i for i in lista if i["visto_em"] != hoje_iso]

    if novos:
        bloco_novos = _lista(novos, hoje_iso)
    else:
        bloco_novos = '<p class="vazio">Nenhuma notícia nova de esporte desde a última verificação.</p>'
    bloco_antigos = _lista(antigos, hoje_iso) if antigos else '<p class="vazio">Ainda não há histórico.</p>'

    aviso_primeira = ""
    if primeira_execucao:
        aviso_primeira = ('<p class="aviso">Primeira execução: tudo o que já estava publicado '
                          'aparece como novo. A partir de amanhã, só o que for realmente novo.</p>')

    linhas_status = []
    for s in status_cidades:
        cls = {"ok": "ok", "aviso": "aviso-s"}.get(s["estado"], "erro")
        rotulo = {"ok": "ok", "aviso": "atenção", "bloqueado": "acesso negado", "erro": "erro"}[s["estado"]]
        linhas_status.append(
            f'<tr><td>{html.escape(s["nome"])}</td>'
            f'<td><span class="pill {cls}">{rotulo}</span></td>'
            f'<td>{html.escape(s["mensagem"])}</td>'
            f'<td><a href="{html.escape(s["url"])}" target="_blank" rel="noopener">abrir site</a></td></tr>'
        )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Esportes na Grande Vitória</title>
<style>
:root {{ --bg:#fafaf7; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e4e3dc;
  --accent:#0b6b4f; --novo:#d97706; --ok:#0b6b4f; --warn:#b45309; --err:#b91c1c; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#14150f; --fg:#ecebe4; --muted:#9a9a90; --card:#1c1d16; --line:#2e2f26;
    --accent:#4ade9d; --novo:#fbbf24; --ok:#4ade9d; --warn:#fbbf24; --err:#f87171; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:760px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }}
.sub {{ color:var(--muted); margin:0 0 20px; font-size:.9rem; }}
h2 {{ font-size:1.1rem; margin:32px 0 8px; padding-bottom:6px; border-bottom:2px solid var(--accent); }}
h3 {{ font-size:.95rem; margin:18px 0 6px; color:var(--accent); text-transform:uppercase; letter-spacing:.04em; }}
ul {{ list-style:none; margin:0; padding:0; }}
li {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:10px 12px; margin-bottom:6px; }}
li a {{ color:var(--fg); text-decoration:none; font-weight:500; }}
li a:hover {{ text-decoration:underline; }}
.data {{ display:block; color:var(--muted); font-size:.8rem; margin-top:2px; }}
.novo {{ background:var(--novo); color:#000; font-size:.7rem; font-weight:700;
  padding:1px 6px; border-radius:99px; text-transform:uppercase; vertical-align:middle; }}
.vazio {{ color:var(--muted); }}
.aviso {{ background:var(--card); border-left:4px solid var(--novo); padding:8px 12px; border-radius:4px; }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
td {{ padding:6px 4px; border-bottom:1px solid var(--line); vertical-align:top; }}
.pill {{ font-size:.72rem; font-weight:700; padding:1px 8px; border-radius:99px; border:1px solid currentColor; white-space:nowrap; }}
.pill.ok {{ color:var(--ok); }} .pill.aviso-s {{ color:var(--warn); }} .pill.erro {{ color:var(--err); }}
details summary {{ cursor:pointer; font-weight:600; margin:24px 0 8px; }}
a {{ color:var(--accent); }}
</style>
</head>
<body>
<main>
<h1>Esportes na Grande Vitória</h1>
<p class="sub">Atualizado em {agora_dt.strftime('%d/%m/%Y às %H:%M')} · Matérias das prefeituras</p>
{aviso_primeira}
<h2>Novas ({len(novos)})</h2>
{bloco_novos}
<details>
<summary>Dos últimos dias ({len(antigos)})</summary>
{bloco_antigos}
</details>
<h2>Situação de cada site</h2>
<table>{''.join(linhas_status)}</table>
<p class="sub" style="margin-top:12px">Sites marcados como "acesso negado" não permitem leitura automática;
use o link "abrir site" para conferir manualmente.</p>
</main>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------
def main() -> int:
    primeira = not ARQ_ITENS.exists()
    itens = carregar_itens()
    hoje_iso = agora().date().isoformat()
    status_cidades = []

    for n, cfg in enumerate(CIDADES):
        if n:
            time.sleep(PAUSA_ENTRE_SITES)
        info = {"nome": cfg["nome"], "url": cfg["url"]}
        try:
            achados, st = coletar_cidade(cfg)
            for i in achados:
                if i["url"] not in itens:
                    itens[i["url"]] = {"titulo": i["titulo"], "cidade": i["cidade"],
                                       "data": i["data"], "visto_em": hoje_iso}
            info.update(st)
        except Bloqueado as e:
            info.update({"estado": "bloqueado", "mensagem": str(e)})
        except Falha as e:
            info.update({"estado": "erro", "mensagem": str(e)})
        except Exception as e:  # nunca derrubar o programa por causa de um site
            info.update({"estado": "erro", "mensagem": f"erro inesperado: {type(e).__name__}"})
        print(f"[{info['estado']}] {cfg['nome']}: {info['mensagem']}")
        status_cidades.append(info)

    limite = (agora().date() - timedelta(days=DIAS_GUARDADOS)).isoformat()
    itens = {u: v for u, v in itens.items() if v["visto_em"] >= limite}

    salvar_itens(itens)
    DOCS_DIR.mkdir(exist_ok=True)
    ARQ_HTML.write_text(gerar_html(itens, status_cidades, primeira), encoding="utf-8")
    print(f"Página gerada: {ARQ_HTML}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
