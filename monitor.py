"""Monitor de ofertas Pokémon 30 anos (best effort, sem acesso privilegiado às lojas)."""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config" / "products.json"
STATE = ROOT / "state.json"
UA = "Mozilla/5.0 (compatible; Pokemon30PriceWatch/1.0; personal noncommercial offer monitoring)"
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}
LOG = logging.getLogger("pokemon30")
BAD_TOKENS = ("25 anos", "25o aniversario", "pokemon 151", "pokemon-151", "pokemon go")


def norm(text: object) -> str:
    s = unicodedata.normalize("NFKD", str(text or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip()


def brl(value: Decimal) -> str:
    return "R$ " + f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def money(raw: object) -> Decimal | None:
    if raw is None:
        return None
    t = re.sub(r"[^\d,.]", "", str(raw))
    if not t:
        return None
    # 1.299,90 -> 1299.90; 1,299.90 -> 1299.90; 299.90 -> 299.90
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        v = Decimal(t)
        return v if v > 0 else None
    except InvalidOperation:
        return None


def is_30_title(title: str) -> bool:
    n = norm(title)
    if any(k in n for k in BAD_TOKENS):
        return False
    return "pokemon" in n and bool(re.search(r"(?:\b30\s*(?:anos|aniversario)\b|celebracao\s*(?:de\s*)?30\b)", n))


def classify(title: str) -> str | None:
    n = norm(title)
    if not is_30_title(n) or re.search(r"\b(kit|varios produtos|sortido)\b", n):
        return None
    if "mewtwo" in n and re.search(r"\bmew\b", n):
        return None  # Anúncio que não identifica qual das duas variantes está à venda
    if re.search(r"\bminiatura\b", n) and "mewtwo" in n:
        return "mewtwo"
    if re.search(r"\bminiatura\b", n) and re.search(r"\bmew\b", n):
        return "mew"
    if "ditto" in n and ("premium" in n or "porta retrato" in n):
        return "ditto"
    if "treinador avancado" in n or re.search(r"\betb\b", n):
        return "etb"
    if "fichario" in n:
        return "fichario"
    if "poster" in n:
        return "poster"
    if "blister" in n and "duplo" in n:
        return "blister_duplo"
    if "blister" in n and "triplo" in n:
        return "blister_triplo"
    if "sylveon" in n:
        return "sylveon"
    if "greninja" in n:
        return "greninja"
    if "6" in n and "booster" in n and ("combo" in n or "pacotes" in n):
        return "combo_6"
    if "espeon" in n and "baralho" in n:
        return "espeon"
    if "umbreon" in n and "baralho" in n:
        return "umbreon"
    if "minilata" in n or "mini lata" in n:
        return "minilata"
    if "dia e noite" in n:
        return None  # Pacote conjunto; não é uma das variantes individuais
    if "colecao dia" in n:
        return "dia"
    if "colecao noite" in n:
        return "noite"
    return None


def same_domain(url: str, expected: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == expected or host.endswith("." + expected)


def safe_url(url: str, expected: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and same_domain(url, expected)


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", "", ""))


def get_html(session: requests.Session, url: str, domain: str) -> str | None:
    if not safe_url(url, domain):
        return None
    try:
        r = session.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if not safe_url(r.url, domain):
            LOG.warning("Redirecionamento não autorizado: %s", r.url)
            return None
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "").lower():
            LOG.warning("Página indisponível (%s): %s", r.status_code, url)
            return None
        return r.text[:3_000_000]
    except requests.RequestException as exc:
        LOG.warning("Erro de acesso em %s: %s", url, exc)
        return None


def objects_deep(tree):
    if isinstance(tree, list):
        for value in tree:
            yield from objects_deep(value)
    elif isinstance(tree, dict):
        yield tree
        for value in tree.values():
            if isinstance(value, (list, dict)):
                yield from objects_deep(value)


def jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            yield from objects_deep(json.loads(tag.string or tag.get_text()))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass


def is_type(node: dict, name: str) -> bool:
    raw = node.get("@type", "")
    return name.lower() in [str(t).split("/")[-1].lower() for t in (raw if isinstance(raw, list) else [raw])]


def seller_name(offer: dict) -> str:
    seller = offer.get("seller")
    if isinstance(seller, dict):
        return str(seller.get("name", ""))
    if isinstance(seller, str):
        return seller
    return ""


def trusted_seller(store: dict, seller: str, trusted: list[str]) -> bool:
    if not store.get("marketplace"):
        return True
    s = norm(seller)
    return bool(s) and any(s == norm(name) for name in trusted)


def offer_from_html(page: str, requested_url: str, store: dict, config: dict) -> dict | None:
    soup = BeautifulSoup(page, "html.parser")
    canonical = soup.find("link", rel="canonical")
    canonical_url = (canonical.get("href") if canonical else "") or requested_url
    if not safe_url(canonical_url, store["domain"]):
        canonical_url = requested_url
    for product in jsonld(soup):
        if not is_type(product, "Product"):
            continue
        title = str(product.get("name", ""))
        category = classify(title)
        if category is None:
            continue
        for offer in (product.get("offers", []) if isinstance(product.get("offers"), list) else [product.get("offers", {})]):
            if not isinstance(offer, dict):
                continue
            if offer.get("priceCurrency", "BRL").upper() != "BRL":
                continue
            price = money(offer.get("price"))
            if price is None and isinstance(offer.get("priceSpecification"), dict):
                price = money(offer["priceSpecification"].get("price"))
            if price is None:
                continue
            availability = norm(offer.get("availability", "")).split("/")[-1]
            if availability not in ("instock", "preorder", "limitedavailability"):
                continue  # Exigir indício explícito de estoque, evitando alertas falsos
            seller = seller_name(offer)
            if not trusted_seller(store, seller, config["trusted_marketplace_sellers"]):
                LOG.info("Vendedor não verificado em %s: %s", store["name"], canonical_url)
                continue
            url = offer.get("url") or canonical_url
            if not safe_url(url, store["domain"]):
                url = canonical_url
            return {"url": clean_url(url), "title": title, "price": price,
                    "category": category, "store": store["name"], "seller": seller or store["name"]}
    return None


def find_candidates(page: str, search_url: str, domain: str, limit: int) -> list[str]:
    soup = BeautifulSoup(page, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()
    for node in soup.find_all("a", href=True):
        anchor = node.get_text(" ", strip=True)[:240]
        href = urljoin(search_url, node.get("href", ""))
        if (not safe_url(href, domain) or not is_30_title(anchor)
                or not classify(anchor)):
            continue
        href = clean_url(href)
        if href not in seen:
            seen.add(href)
            candidates.append(href)
            if len(candidates) >= limit:
                break
    return candidates


def telegram_send(session: requests.Session, text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        LOG.warning("TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID ainda não configurados")
        return False
    try:
        resp = session.post(f"https://api.telegram.org/bot{token}/sendMessage",
                            data={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                            timeout=12)
        if not resp.ok or not resp.json().get("ok"):
            LOG.warning("Telegram recusou mensagem (HTTP %s)", resp.status_code)
            return False
        return True
    except (requests.RequestException, ValueError):
        LOG.warning("Falha no envio ao Telegram; revise os Secrets ou se enviou /start ao bot")
        return False


def message(offer: dict, limit: Decimal) -> str:
    fmt = lambda s: html.escape(str(s), quote=True)
    time = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    return ("🚨 <b>POKÉMON 30 ANOS — OFERTA</b>\n"
            f"<b>{fmt(offer['title'])}</b>\n"
            f"Preço anunciado: <b>{brl(offer['price'])}</b> (limite: {brl(limit)})\n"
            f"Loja: {fmt(offer['store'])}\nVendedor: {fmt(offer['seller'])}\n"
            "<i>Cupom e frete não verificados; confira no carrinho antes de comprar.</i>\n"
            f"Consulta: {time}\n" f"<a href=\"{fmt(offer['url'])}\">Abrir produto</a>")


def monitor():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    limits = {k: Decimal(str(v)) for k, v in config["thresholds_brl"].items()}
    stores = config["stores"]
    with requests.Session() as session:
        listings = []
        # Um catálogo público por execução; o agendamento total é de cinco minutos.
        # Isso limita requisições em sites que permitem consulta, sem ultrapassar tarifas de APIs.
        slot = int(datetime.now(timezone.utc).timestamp() // 300)
        selected = stores[slot % len(stores)]
        LOG.info("Buscando candidatos na loja: %s", selected["name"])
        listing_html = get_html(session, selected["search_url"], selected["domain"])
        if listing_html:
            urls = find_candidates(listing_html, selected["search_url"], selected["domain"],
                                   int(config["max_listings_per_store"]))
            listings += [(url, selected) for url in urls]
            LOG.info("Anúncios candidatos: %s", len(urls))
        else:
            LOG.warning("Busca da loja %s bloqueada/indisponível", selected["name"])
        # URLs individuais adicionadas manualmente são conferidas em TODAS as execuções.
        for item in config.get("watched_product_urls", []):
            if isinstance(item, dict):
                host = (urlparse(item.get("url", "")).hostname or "").lower()
                found = next((s for s in stores if same_domain("https://" + host, s["domain"])), None)
                if found:
                    listings.append((item["url"], found))
        sent = 0
        seen = set()
        for url, store in listings:
            key = clean_url(url)
            if key in seen:
                continue
            seen.add(key)
            page = get_html(session, url, store["domain"])
            if not page:
                continue
            result = offer_from_html(page, url, store, config)
            if not result:
                continue
            category = result["category"]
            if result["price"] >= limits[category]:
                continue
            key = result["url"]
            best = money(state.get(key))
            if best is not None and result["price"] >= best:
                continue
            if telegram_send(session, message(result, limits[category])):
                state[key] = str(result["price"])
                sent += 1
                LOG.info("Alerta enviado: %s a %s", result["title"], brl(result["price"]))
        if sent:
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        LOG.info("Execução concluída; alertas enviados: %s", sent)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-telegram", action="store_true", help="Envia mensagem de teste ao bot")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.test_telegram:
        with requests.Session() as session:
            ok = telegram_send(session, "✅ Teste do monitor Pokémon 30 Anos: Telegram configurado com sucesso.")
        sys.exit(0 if ok else 1)
    monitor()


if __name__ == "__main__":
    main()
