#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, json, base64, unicodedata
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI
import requests

# ---------- Chemins ----------
ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
ARTICLES = ROOT / "articles"
IMAGES = ROOT / "images"
TEMPLATES = ROOT / "templates"
TEMPLATE = TEMPLATES / "template_cuisine.html"

# ---------- Utilitaires ----------
def die(msg: str):
    print(f"❌ {msg}")
    sys.exit(1)

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "recette"

def html_to_text(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)

def make_excerpt(intro_html: str, min_len=120, max_len=160) -> str:
    txt = re.sub(r"\s+", " ", html_to_text(intro_html)).strip()
    if len(txt) <= max_len:
        return txt
    cut = txt.rfind(" ", 0, max_len)
    if cut < min_len: cut = max_len
    return txt[:cut].strip()

def strip_inline_refs(html: str) -> str:
    html = re.sub(r"\[\s*\d+\s*\]", "", html)
    html = re.sub(r"<sup>\s*\d+\s*</sup>", "", html, flags=re.I)
    html = re.sub(r"<sup>\s*\[\s*\d+\s*\]\s*</sup>", "", html, flags=re.I)
    return html

def ensure_dirs():
    if not INDEX.exists():
        die("index.html manquant à la racine.")
    ARTICLES.mkdir(exist_ok=True)
    IMAGES.mkdir(exist_ok=True)
    TEMPLATES.mkdir(exist_ok=True)

# ---------- OpenAI ----------
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    die("OPENAI_API_KEY manquant (Secrets GitHub > Actions).")
client = OpenAI(api_key=api_key)

# ---------- Génération recette (JSON strict) ----------
PROMPT_JSON = """
Tu es un chef spécialisé en cuisine d'Asie. Génère UNE recette simple, familiale et savoureuse
(durée totale ~20 à 40 min), avec des ingrédients faciles à trouver en France.

Réponds STRICTEMENT en JSON (pas de texte hors JSON) au format :
{
  "title": "Titre court",
  "intro": "Petit paragraphe d'introduction (2-3 phrases, ton convivial).",
  "ingredients_2": ["…", "…"],
  "ingredients_3": ["…", "…"],
  "ingredients_4": ["…", "…"],
  "steps": ["Étape 1 …", "Étape 2 …", "…"],
  "image_keywords": "mots clefs courts décrivant le plat et le style de présentation"
}

Contraintes :
- Cuisine asiatique (Chine, Japon, Thaïlande, Vietnam, Corée, etc.).
- Pas d'alcool obligatoire ; propose des alternatives si utile.
- N'ajoute AUCUNE numérotation de références ([1], [2], etc.).
"""

def generate_recipe_data() -> dict:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": PROMPT_JSON}],
        temperature=0.7,
    )
    raw = resp.choices[0].message.content.strip()
    try:
        data = json.loads(raw)
    except Exception as e:
        die(f"JSON recette invalide: {e}\n---\n{raw[:4000]}")
    return data

# ---------- Image héro ----------
def save_bytes(path: Path, data: bytes):
    path.write_bytes(data)

def try_download(url: str, timeout=30) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"ℹ️ Téléchargement image échec: {e}")
        return None

def generate_food_image(title: str, keywords: str, out_path: Path) -> bool:
    prompts = [
        f"Food photography, high-end editorial, soft daylight, shallow depth of field. "
        f"Dish: {title}. Keywords: {keywords}. Serve on a beautiful plate, elegant cutlery and chopsticks on side. "
        f"Asian table setting, neutral background, appetizing, realistic.",
        f"Professional food photo of {title}. Gorgeous plating, chopsticks, clean linen napkin, restaurant quality."
    ]
    sizes = ["1024x768", "768x768", "1200x800"]
    for p in prompts:
        for size in sizes:
            try:
                print(f"→ Génération image ({size})…")
                img = client.images.generate(model="gpt-image-1", prompt=p, size=size)
                d = img.data[0]
                if getattr(d, "b64_json", None):
                    save_bytes(out_path, base64.b64decode(d.b64_json)); print("✅ Image (b64)"); return True
                if getattr(d, "url", None):
                    content = try_download(d.url)
                    if content: save_bytes(out_path, content); print("✅ Image (url)"); return True
            except Exception as e:
                print(f"ℹ️ Tentative image échouée ({size}): {e}")
                continue
    print("⚠️ Impossible de générer l’image.")
    return False

# ---------- Rendu article ----------
FALLBACK_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{TITLE}}</title></head><body>
<h1>{{TITLE}}</h1>
<figure class="img"><img src="/images/{{HERO_FILENAME}}" alt="{{HERO_ALT}}"></figure>
{{INTRO_HTML}}
<h2>Ingrédients</h2>
<h3>Pour 2 personnes</h3>{{INGREDIENTS_2}}
<h3>Pour 3 personnes</h3>{{INGREDIENTS_3}}
<h3>Pour 4 personnes</h3>{{INGREDIENTS_4}}
<h2>Étapes</h2>
{{STEPS_HTML}}
{{SCHEMA_JSON}}
</body></html>"""

def make_ul(items: list[str]) -> str:
    return "<ul>\n" + "\n".join(f"  <li>{re.sub(r'[\\n\\r]+',' ',i).strip()}</li>" for i in items) + "\n</ul>"

def build_steps(steps: list[str]) -> str:
    # s’adapte aux templates type “.steps > .step”
    return "\n".join(f'<div class="step"><p>{re.sub(r"[\\n\\r]+"," ", s).strip()}</p></div>' for s in steps)

def build_schema_json(title, intro, image_name, steps):
    data = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": title,
        "description": intro,
        "recipeCuisine": "Asiatique",
        "image": [f"/images/{image_name}"],
        "recipeInstructions": [{"@type":"HowToStep","text": s} for s in steps]
    }
    return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>'

# ---------- Mise à jour index ----------
def ensure_feed_markers(html: str) -> str:
    if "<!-- FEED:start -->" in html and "<!-- FEED:end -->" in html:
        return html
    m = re.search(r"<body[^>]*>", html, flags=re.I)
    pos = m.end() if m else 0
    return html[:pos] + '\n<main class="grid">\n<!-- FEED:start -->\n<!-- FEED:end -->\n</main>\n' + html[pos:]

# ---------- MAIN ----------
def main():
    ensure_dirs()

    data = generate_recipe_data()
    title = data.get("title","Recette asiatique")
    intro = data.get("intro","Une recette simple et savoureuse.")
    ing2, ing3, ing4 = data.get("ingredients_2",[]), data.get("ingredients_3",[]), data.get("ingredients_4",[])
    steps = data.get("steps",[])
    keywords = data.get("image_keywords","asian noodles, chicken, glossy sauce, chopsticks")

    # Nettoyages & HTML
    intro_html = f'<p class="lead">{strip_inline_refs(intro)}</p>'
    ingredients_2 = make_ul(ing2)
    ingredients_3 = make_ul(ing3)
    ingredients_4 = make_ul(ing4)
    steps_html = build_steps(steps)

    now = datetime.now(timezone.utc).astimezone()
    date_str = now.strftime("%d/%m/%Y")
    stamp = now.strftime("%Y-%m-%d %H:%M:%S %z")
    slug = f"{now.date().isoformat()}-{slugify(title)[:60]}"
    article_filename = f"{slug}.html"
    hero_filename = f"{slug}-hero.jpg"
    hero_alt = f"Photo de {title}"

    # Image
    has_img = generate_food_image(title, keywords, IMAGES / hero_filename)

    # Template
    template = TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.exists() else FALLBACK_TEMPLATE
    schema_json = build_schema_json(title, intro, hero_filename if has_img else "", steps)

    article_html = (
        template
        .replace("{{TITLE}}", title)
        .replace("{{HERO_FILENAME}}", hero_filename if has_img else "")
        .replace("{{HERO_ALT}}", hero_alt)
        .replace("{{INTRO_HTML}}", intro_html)
        .replace("{{INGREDIENTS_2}}", ingredients_2)
        .replace("{{INGREDIENTS_3}}", ingredients_3)
        .replace("{{INGREDIENTS_4}}", ingredients_4)
        .replace("{{STEPS_HTML}}", steps_html)
        .replace("{{SCHEMA_JSON}}", schema_json if "{{SCHEMA_JSON}}" in template else "")
    )

    if has_img:
        # S’assurer que l’article (dans /articles/) pointe vers /images/...
        article_html = re.sub(r'src=["\']/?images/\{\{HERO_FILENAME\}\}["\']',
                              f'src="/images/{hero_filename}"', article_html, flags=re.I)
    else:
        # Retirer <figure class="img"> si présent
        article_html = re.sub(r'\s*<figure\s+class="img">[\s\S]*?</figure>\s*',
                              '\n<div style="height:24px"></div>\n', article_html, flags=re.I)

    (ARTICLES / article_filename).write_text(article_html, encoding="utf-8")
    print(f"✅ Recette écrite: articles/{article_filename}")

    # Index
    idx = INDEX.read_text(encoding="utf-8")
    idx = ensure_feed_markers(idx)

    thumb = (
        f'<img src="images/{hero_filename}" alt="{hero_alt}">'
        if has_img else
        '<div style="aspect-ratio:4/3;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.05)"></div>'
    )
    description = make_excerpt(intro_html)

    card = f"""
      <!-- card-{slug} -->
      <a class="card" href="articles/{article_filename}">
        <figure>
          {thumb}
          <figcaption>
            <div class="title">{title}</div>
            <div class="date">{date_str}</div>
          </figcaption>
        </figure>
      </a>
    """.rstrip()

    idx = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card, idx, count=1, flags=re.S)
    idx += f"\n<!-- automated-build {stamp} -->\n"
    INDEX.write_text(idx, encoding="utf-8")
    print("✅ index.html mis à jour")

if __name__ == "__main__":
    main()
