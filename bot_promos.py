#!/usr/bin/env python3
"""Bot de veille : grosses promos et erreurs de prix en Europe.
Alertes sur Telegram et/ou Discord.

Installation :  pip install requests feedparser
Lancement    :
    export TELEGRAM_TOKEN="123456:ABC..."
    export TELEGRAM_CHAT_ID="123456789"
    export DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."   # optionnel
    python bot_promos.py
(Renseigne l'un, l'autre, ou les deux.)
"""
import html
import json
import os
import re
import time
from pathlib import Path

import feedparser
import requests

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
DISCORD = os.environ.get("DISCORD_WEBHOOK", "")

INTERVALLE = 120        # secondes entre deux passages
SEUIL_REMISE = 60       # % minimum pour alerter
SEEN_FILE = Path("seen.json")

# --- SOURCES (flux RSS) -------------------------------------------------
# Réseau Pepper : le plus gros agrégateur de bons plans européen
PEPPER = {
    "Dealabs (FR)":       "https://www.dealabs.com/rss/nouveaux",
    "mydealz (DE)":       "https://www.mydealz.de/rss/nouveaux",
    "Preisjäger (AT)":    "https://www.preisjaeger.at/rss/nouveaux",
    "Chollometro (ES)":   "https://www.chollometro.com/rss/nuevos",
    "Pepper (IT)":        "https://www.pepper.it/rss/nuovi",
    "Pepper (PL)":        "https://www.pepper.pl/rss/nowe",
    "Pepper (NL)":        "https://www.pepper.nl/rss/nieuw",
    "HotUKDeals (UK)":    "https://www.hotukdeals.com/rss/all",
}
# Reddit : chaque subreddit a un flux RSS en ajoutant .rss
REDDIT = {
    "r/bonplans (FR)":     "https://www.reddit.com/r/bonplans/new/.rss",
    "r/BonPlansFrance":    "https://www.reddit.com/r/BonPlansFrance/new/.rss",
    "r/HotUKDeals (UK)":   "https://www.reddit.com/r/HotUKDeals/new/.rss",
    "r/ukdeals (UK)":      "https://www.reddit.com/r/ukdeals/new/.rss",
    "r/mydealz (DE)":      "https://www.reddit.com/r/mydealz/new/.rss",
    "r/Chollometro (ES)":  "https://www.reddit.com/r/Chollometro/new/.rss",
    "r/Preisfehler (DE)":  "https://www.reddit.com/r/Preisfehler/new/.rss",
    "r/PriceMistakes":     "https://www.reddit.com/r/PriceMistakes/new/.rss",
    "r/deals":             "https://www.reddit.com/r/deals/new/.rss",
}
# Ajoute ici tes propres flux (blogs de bons plans, etc.)
AUTRES = {
    # "Mon blog": "https://exemple.com/feed",
}
FLUX = {**PEPPER, **REDDIT, **AUTRES}

# --- DÉTECTION ----------------------------------------------------------
MOTS_CLES = [
    "erreur de prix", "erreur prix", "bug de prix", "bug prix",
    "price error", "pricing error", "price mistake", "pricing mistake",
    "preisfehler", "fehlerpreis",
    "error de precio", "fallo de precio", "error precio",
    "errore di prezzo", "errore prezzo",
    "błąd cenowy", "blad cenowy", "pomyłka cenowa",
    "prijsfout", "foutieve prijs",
    "erro de preço", "erro de preco",
]


def charger_vus():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except (ValueError, OSError):
            pass
    return set()


def sauver_vus(vus):
    SEEN_FILE.write_text(json.dumps(list(vus)[-8000:]))


def remise_dans(texte):
    valeurs = [int(m) for m in re.findall(r"-\s?(\d{2,3})\s?%", texte)]
    return max(valeurs) if valeurs else 0


def est_interessant(titre):
    t = titre.lower()
    if any(k in t for k in MOTS_CLES):
        return "🚨 Erreur de prix probable"
    r = remise_dans(titre)
    if r >= SEUIL_REMISE:
        return f"🔥 Remise de {r} %"
    return None


# --- NOTIFICATIONS ------------------------------------------------------
def envoyer_telegram(source, motif, titre, lien):
    if not (TG_TOKEN and TG_CHAT):
        return
    texte = (f"<b>{html.escape(motif)}</b>\n{html.escape(titre)}\n"
             f"<i>{html.escape(source)}</i>\n{html.escape(lien)}")
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": texte, "parse_mode": "HTML"},
            timeout=10,
        )
    except requests.RequestException as e:
        print("Erreur Telegram :", e)


def envoyer_discord(source, motif, titre, lien):
    if not DISCORD:
        return
    payload = {"embeds": [{
        "title": titre[:250], "url": lien,
        "description": f"**{motif}**\nSource : {source}", "color": 15158332,
    }]}
    try:
        requests.post(DISCORD, json=payload, timeout=10)
    except requests.RequestException as e:
        print("Erreur Discord :", e)


def alerter(source, motif, titre, lien):
    print(f"[{source}] {motif} : {titre} -> {lien}")
    envoyer_telegram(source, motif, titre, lien)
    envoyer_discord(source, motif, titre, lien)


# --- BOUCLE PRINCIPALE --------------------------------------------------
def lire(url):
    # User-Agent de navigateur : certains sites (Reddit) refusent le défaut
    return feedparser.parse(url, agent="Mozilla/5.0 (compatible; PromoBot/1.0)")


def passage(vus, silencieux, verbose=False):
    for source, url in FLUX.items():
        try:
            flux = lire(url)
        except Exception as e:
            print(f"Flux {source} indisponible :", e)
            continue
        if verbose:
            etat = f"{len(flux.entries)} offres" if flux.entries else "VIDE/ERREUR"
            print(f"  {source}: {etat}")
        for e in flux.entries:
            ident = e.get("id") or e.get("link")
            if not ident or ident in vus:
                continue
            vus.add(ident)
            if silencieux:
                continue
            motif = est_interessant(e.get("title", ""))
            if motif:
                alerter(source, motif, e.get("title", ""), e.get("link", ""))
        time.sleep(1)  # politesse envers les serveurs


def main():
    if not (TG_TOKEN and TG_CHAT) and not DISCORD:
        print("Aucune destination configurée : les alertes s'afficheront ici seulement.")
    vus = charger_vus()
    premier = not vus
    if os.environ.get("RUN_ONCE"):
        # Mode "un seul passage" : pour GitHub Actions (lancé toutes les 5 min)
        passage(vus, silencieux=premier)
        sauver_vus(vus)
        return
    print("Test des flux au démarrage :")
    passage(vus, silencieux=premier, verbose=True)
    sauver_vus(vus)
    while True:
        time.sleep(INTERVALLE)
        passage(vus, silencieux=False)
        sauver_vus(vus)


if __name__ == "__main__":
    main()
