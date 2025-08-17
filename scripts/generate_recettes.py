#!/usr/bin/env python3
import os
from datetime import datetime, date, timezone
from pathlib import Path
from openai import OpenAI
import base64
import json, re
import unicodedata

# --- Dossiers ---
ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"
IMAGES_DIR = ROOT / "images"
TEMPLATES_DIR = ROOT / "templates"
INDEX_FILE = ROOT / "index.html"
TEMPLATE_FILE = TEMPLATES_DIR / "template_cuisine.html"

ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# OpenAI client
# =========================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise SystemExit("❌ Erreur : OPENAI_API_KEY manquant (ajoute-le dans GitHub > Settings > Secrets and variables > Actions).")
client = OpenAI(api_key=api_key)

# =========================
# Utils
# =========================
def slugify(s: str) -> str:
    """ASCII, minuscules, remplace tout ce qui n'est pas [a-z0-9] par _"""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s

def existing_article_slugs() -> set:
    """Liste des slugs (partie après la date) déjà publiés dans /articles."""
    slugs = set()
    for p in ARTICLES_DIR.glob("*.html"):
        stem = p.stem  # ex: 2025-08-17-nouilles_sautees_au_poulet
        if "-" in stem:
            try:
                slugs.add(stem.split("-", 1)[1])  # garde la partie après la date
            except Exception:
                pass
    return slugs

def theme_of_the_day() -> str:
    """Thème (ingrédient/style) qui varie chaque jour pour forcer la diversité."""
    themes = [
        "poulet", "boeuf", "porc", "tofu végétarien", "crevettes",
        "canard", "nouilles", "riz", "soupe", "curry",
        "salade", "dessert asiatique", "poisson", "agneau",
        "dim sum", "wok express", "street food asiatique", "vietnamien",
        "thaï", "coréen", "japonais", "indien", "malaisien", "indonésien", "chinois"
    ]
    idx = datetime.now().toordinal() % len(themes)
    return themes[idx]

# =========================
# Génération IA
# =========================
def generate_recette_via_ai() -> dict:
    """
    Génére une recette asiatique en JSON structuré, en évitant les doublons
    ET en imposant le même set d'ingrédients pour 2/3/4 personnes.
    """
    banned = sorted(existing_article_slugs())
    theme = theme_of_the_day()

    base_prompt = f"""
Tu es un chef asiatique. Thème du jour : "{theme}".

Interdictions :
- Ne propose PAS une recette dont le titre (après slugification ASCII) correspond à l'un des slugs existants :
{", ".join(banned) if banned else "(aucun)"}

Objectif :
Génère UNE recette asiatique simple en français, au format JSON EXACT ci-dessous (aucun texte avant/après).

Schéma OBLIGATOIRE (respecte la casse des clés) :
{{
  "titre": "...",
  "description": "...",
  "duree_preparation": "... (ex: 25 min)",
  "duree_preparation_iso": "... (ex: PT25M)",
  "etapes": ["...", "...", "..."],
  "ingredients_items": [
    {{
      "nom": "Riz jasmin",
      "unite": "g",            // ou "ml", "pièce", "", etc.
      "pour_2": 150,
      "pour_3": 225,
      "pour_4": 300
    }}
  ],
  "astuce": "...",
  "conseils": ["...", "..."]
}}

Contraintes IMPORTANTES :
- Le tableau "ingredients_items" contient le même inventaire d'ingrédients ; seules les valeurs "pour_2/pour_3/pour_4" varient.
- Ne mets pas les quantités dans "nom" (pas de "200 g de riz" dans le nom). Les quantités sont dans pour_2/pour_3/pour_4 et l'unité dans "unite".
- Utilise un plat identifiable d'Asie. Donne UNIQUEMENT le JSON valide.
"""

    last_data = None
    for attempt in range(4):
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=base_prompt,
            temperature=0.95,
            max_output_tokens=1000,
        )
        raw = (resp.output_text or "").strip()
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            base_prompt += "\nLe JSON n'a pas été détecté. Renvoie UNIQUEMENT le JSON.\n"
            continue

        try:
            data = json.loads(m.group(0))
            last_data = data
        except json.JSONDecodeError:
            base_prompt += "\nLe JSON était invalide. Renvoie un JSON strictement valide.\n"
            continue

        # validations minimales
        required = ["titre","description","duree_preparation","duree_preparation_iso","etapes","astuce","conseils"]
        if any(k not in data for k in required):
            base_prompt += "\nDes clés manquent. Renvoie le JSON complet avec toutes les clés requises.\n"
            continue

        # on accepte soit le nouveau schéma "ingredients_items", soit ancien fallback "ingredients"
        if "ingredients_items" not in data and "ingredients" not in data:
            base_prompt += "\nLes ingrédients manquent. Utilise impérativement 'ingredients_items'.\n"
            continue

        # Anti-doublon sur le titre
        slug = slugify(data["titre"])
        if slug in banned:
            base_prompt += f"\nATTENTION : Le slug '{slug}' existe déjà. Propose un autre plat au même thème.\n"
            continue

        # Si l'IA a renvoyé l'ancien format, on convertit en items cohérents
        if "ingredients_items" not in data and "ingredients" in data:
            ing = data["ingredients"]

            def clean_name(s):
                # supprime quantités style "200 g", "1 c. à s.", etc., au début
                s = re.sub(r"^\s*\d+[.,]?\d*\s*\w*\.?\s*(de|d')?\s*", "", s, flags=re.I)
                return s.strip().strip("-•").strip()

            sets = []
            for key in ["2","3","4"]:
                if key in ing and isinstance(ing[key], list):
                    names = [clean_name(x) for x in ing[key]]
                    sets.append(set(n for n in names if n))
            base = set.intersection(*sets) if sets else set()
            if not base and sets:
                base = set.union(*sets)

            items = []
            for name in sorted(base):
                items.append({"nom": name, "unite": "", "pour_2": 0, "pour_3": 0, "pour_4": 0})
            data["ingredients_items"] = items
            data.pop("ingredients", None)

        # Vérifier cohérence des items
        items = data.get("ingredients_items", [])
        if not isinstance(items, list) or not items:
            base_prompt += "\n'ingredients_items' est vide. Recommence avec des ingrédients structurés.\n"
            continue
        ok = all(all(k in it for k in ["nom","unite","pour_2","pour_3","pour_4"]) for it in items)
        if not ok:
            base_prompt += "\nChaque entrée de 'ingredients_items' doit contenir nom, unite, pour_2, pour_3, pour_4.\n"
            continue

        return data

    # Fallback (rare)
    return last_data

def generate_image(titre: str) -> str:
    """Génère une image réaliste de la recette avec couverts + baguettes."""
    prompt = (
        f"Photo réaliste d'un plat asiatique : {titre}, servi dans une belle assiette, "
        f"avec des baguettes élégantes et des couverts modernes, style photo culinaire professionnelle."
    )
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024"
    )
    b64 = response.data[0].b64_json
    img_bytes = base64.b64decode(b64)

    today = date.today().isoformat()
    filename = f"{today}-{slugify(titre)}.jpg"
    filepath = IMAGES_DIR / filename
    with open(filepath, "wb") as f:
        f.write(img_bytes)

    # Chemin ABSOLU pour que /articles/... affiche bien l'image
    return f"/images/{filename}"

def generate_html_from_template(data: dict, image_path: str) -> str:
    """Insère les données dans le template HTML de recette."""
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    # Étapes
    etapes_html = "\n".join([f'<div class="step"><p>{e}</p></div>' for e in data["etapes"]])

    # Ingrédients — on construit 3 listes à partir du schéma 'ingredients_items'
    items = data.get("ingredients_items", [])

    def fmt(q, u, n):
        # jolies quantités: 2.0 -> 2
        if isinstance(q, float) and q.is_integer():
            q = int(q)
        if u:
            return f"{q} {u} — {n}" if q else n
        else:
            return f"{q} — {n}" if q else n

    ing2 = "\n".join([f"<li>{fmt(it['pour_2'], it.get('unite',''), it['nom'])}</li>" for it in items])
    ing3 = "\n".join([f"<li>{fmt(it['pour_3'], it.get('unite',''), it['nom'])}</li>" for it in items])
    ing4 = "\n".join([f"<li>{fmt(it['pour_4'], it.get('unite',''), it['nom'])}</li>" for it in items])

    ingredients_html = {
        "2": f"<ul>{ing2}</ul>",
        "3": f"<ul>{ing3}</ul>",
        "4": f"<ul>{ing4}</ul>",
    }

    # Schéma HowTo (SEO)
    schema_etapes_json = ",\n        ".join(
        [f'{{"@type":"HowToStep","text":"{e}"}}' for e in data["etapes"]]
    )

    html = template
    html = html.replace("{{TITRE_RECETTE}}", data["titre"])
    html = html.replace("{{DESCRIPTION_RECETTE}}", data["description"])
    html = html.replace("{{IMAGE_RECETTE}}", image_path)  # => on passe bien "/images/xxx.jpg"
    html = html.replace("{{DUREE_PREPARATION}}", data["duree_preparation"])
    html = html.replace("{{DUREE_PREPARATION_ISO}}", data["duree_preparation_iso"])
    html = html.replace("{{ETAPES_HTML}}", etapes_html)
    html = html.replace("{{INGREDIENTS_2_HTML}}", ingredients_html["2"])
    html = html.replace("{{INGREDIENTS_3_HTML}}", ingredients_html["3"])
    html = html.replace("{{INGREDIENTS_4_HTML}}", ingredients_html["4"])
    html = html.replace("{{ASTUCE}}", data["astuce"])
    html = html.replace("{{CONSEIL_1}}", data["conseils"][0])
    html = html.replace("{{CONSEIL_2}}", data["conseils"][1])
    html = html.replace("{{SCHEMA_ETAPES_JSON}}", schema_etapes_json)

    return html

def save_article(html: str, titre: str) -> Path:
    today = date.today().isoformat()
    filename = f"{today}-{slugify(titre)}.html"
    filepath = ARTICLES_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filepath

# ============ Helpers ============
def _html_to_text(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("\n", " ").strip()

def _make_excerpt(desc: str, max_len=160, min_len=150) -> str:
    txt = re.sub(r"\s+", " ", _html_to_text(desc))
    if len(txt) <= max_len:
        return txt
    cut = txt.rfind(" ", 0, max_len)
    if cut < min_len:
        cut = max_len
    return txt[:cut].strip()

# ============ Index update ============
def update_index(titre: str, desc: str, image: str, article_file: Path) -> None:
    """Injecte une carte dans le bloc FEED sans écraser l’existant."""
    date_str = datetime.now().strftime("%d/%m/%Y")

    href = f"articles/{os.path.basename(article_file)}"
    img_src = image.lstrip("/")
    if not img_src.startswith("images/"):
        img_src = f"images/{os.path.basename(img_src)}"

    excerpt = _make_excerpt(desc, 160, 150)

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        idx_html = f.read()

    # S’assurer que les marqueurs FEED existent
    if "<!-- FEED:start -->" not in idx_html or "<!-- FEED:end -->" not in idx_html:
        m = re.search(r"<div[^>]*class=[\"'][^\"']*\bgrid\b[^\"']*[\"'][^>]*>", idx_html, flags=re.I)
        if not m:
            raise SystemExit("Impossible de trouver la grille .grid pour insérer le feed.")
        pos = m.end()
        idx_html = idx_html[:pos] + "\n<!-- FEED:start -->\n<!-- FEED:end -->\n" + idx_html[pos:]

    # Carte
    card_html = f"""
          <!-- card-{os.path.splitext(os.path.basename(article_file))[0]} -->
          <article class="card">
            <a class="thumb" href="{href}" aria-label="Lire : {titre}">
              <img src="{img_src}" alt="{titre}">
            </a>
            <div class="card-body">
              <h2 class="title">{titre}</h2>
              <p class="excerpt">{excerpt}</p>
              <div class="meta">
                <span class="badge">Recette</span>
                <span>Publié le {date_str}</span>
              </div>
              <a class="link" href="{href}">Lire la recette</a>
            </div>
          </article>""".rstrip()

    # Injection + déduplication par href
    def inject(feed_block: str) -> str:
        feed_block = re.sub(
            rf'\s*<!-- card-[^-]+? -->\s*<article class="card">[\s\S]*?href="{re.escape(href)}"[\s\S]*?</article>',
            "", feed_block, flags=re.I
        )
        feed_block = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card_html, feed_block, count=1, flags=re.S)
        return feed_block

    idx_html = re.sub(r"<!-- FEED:start -->[\s\S]*?<!-- FEED:end -->",
                      lambda m: inject(m.group(0)), idx_html, count=1, flags=re.S)

    # Horodatage build
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
    idx_html = idx_html + f"\n<!-- automated-build {stamp} -->\n"

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(idx_html)

# =========================
# Main
# =========================
def main():
    print("🎯 Thème du jour :", theme_of_the_day())
    data = generate_recette_via_ai()
    if not data:
        raise SystemExit("❌ Impossible de générer la recette.")

    image_path = generate_image(data["titre"])
    html = generate_html_from_template(data, image_path)
    article_file = save_article(html, data["titre"])
    update_index(data["titre"], data["description"], image_path, article_file)
    print(f"✅ Recette publiée : {article_file}")

if __name__ == "__main__":
    main()
