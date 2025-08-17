#!/usr/bin/env python3
import os
import datetime
from pathlib import Path
from openai import OpenAI
import base64
import json, re

# --- Dossiers ---
ROOT = Path(__file__).resolve().parent.parent
ARTICLES_DIR = ROOT / "articles"
IMAGES_DIR = ROOT / "images"
TEMPLATES_DIR = ROOT / "templates"
INDEX_FILE = ROOT / "index.html"
TEMPLATE_FILE = TEMPLATES_DIR / "template_cuisine.html"

# =========================
# OpenAI client
# =========================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise SystemExit("❌ Erreur : OPENAI_API_KEY manquant (ajoute-le dans GitHub > Settings > Secrets and variables > Actions).")
client = OpenAI(api_key=api_key)


def generate_recette_via_ai():
    """Génère une recette asiatique simple en JSON structuré."""
    prompt = """
    Génère une recette asiatique simple en français, sous format JSON structuré avec les clés EXACTES :
    {
      "titre": "...",
      "description": "...",
      "duree_preparation": "... (ex: 25 min)",
      "duree_preparation_iso": "... (ex: PT25M)",
      "etapes": ["...", "...", "..."],
      "ingredients": {
        "2": ["...", "..."],
        "3": ["...", "..."],
        "4": ["...", "..."]
      },
      "astuce": "...",
      "conseils": ["...", "..."]
    }
    Donne UNIQUEMENT le JSON valide (aucun texte avant/après).
    """
    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.7,
        max_output_tokens=800,
    )

    raw = (resp.output_text or "").strip()
    if not raw:
        raise ValueError("Réponse vide de l'IA")

    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        raise ValueError(f"Aucun JSON trouvé dans la réponse: {raw[:200]}")
    json_str = m.group(0)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalide: {e}\n---\n{json_str[:500]}")

    # Vérifications minimales
    required = ["titre","description","duree_preparation","duree_preparation_iso","etapes","ingredients","astuce","conseils"]
    for k in required:
        if k not in data:
            raise ValueError(f"Clé manquante dans le JSON: {k}")
    for ppl in ["2","3","4"]:
        if ppl not in data["ingredients"]:
            raise ValueError(f"Ingrédients manquants pour {ppl} personnes")

    return data


def generate_image(titre):
    """Génère une image réaliste de la recette avec couverts + baguettes."""
    prompt = f"Photo réaliste d'un plat asiatique : {titre}, servi dans une belle assiette, avec des baguettes élégantes et des couverts modernes, style photo culinaire professionnelle."
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024"  # format accepté
    )
    b64 = response.data[0].b64_json
    img_bytes = base64.b64decode(b64)

    today = datetime.date.today().isoformat()
    filename = f"{today}-{titre.replace(' ', '_')}.jpg"
    filepath = IMAGES_DIR / filename
    with open(filepath, "wb") as f:
        f.write(img_bytes)

    return f"images/{filename}"


def generate_html_from_template(data: dict, image_path: str) -> str:
    """Insère les données dans le template HTML de recette."""
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    etapes_html = "\n".join([f'<div class="step"><p>{e}</p></div>' for e in data["etapes"]])

    ingredients_html = {}
    for personnes in ["2", "3", "4"]:
        ing_list = "\n".join([f"<li>{ing}</li>" for ing in data["ingredients"][personnes]])
        ingredients_html[personnes] = f"<ul>{ing_list}</ul>"

    schema_etapes_json = ",\n        ".join(
        [f'{{"@type":"HowToStep","text":"{e}"}}' for e in data["etapes"]]
    )

    html = template
    html = html.replace("{{TITRE_RECETTE}}", data["titre"])
    html = html.replace("{{DESCRIPTION_RECETTE}}", data["description"])
    html = html.replace("{{IMAGE_RECETTE}}", image_path)
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


def save_article(html: str, titre: str):
    today = datetime.date.today().isoformat()
    filename = f"{today}-{titre.replace(' ', '_')}.html"
    filepath = ARTICLES_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filepath


def update_index(titre, desc, image, article_file):
    """Ajoute la dernière recette en haut de la grille dans index.html."""
    from datetime import datetime
    date_str = datetime.now().strftime("%d/%m/%Y")

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index_content = f.read()

    card_html = f"""
  <a class="card" href="/articles/{os.path.basename(article_file)}">
    <figure>
      <img src="/{image.lstrip('/')}" alt="{titre}" loading="lazy" />
      <figcaption>
        <div class="title">{titre}</div>
        <div class="date">{date_str}</div>
      </figcaption>
    </figure>
  </a>""".rstrip()

    if "<!--RECIPES-->" in index_content:
        index_content = index_content.replace("<!--RECIPES-->", f"<!--RECIPES-->\n{card_html}\n", 1)
    else:
        index_content = index_content.replace(
            '<div class="grid" id="grid">',
            f'<div class="grid" id="grid">\n<!--RECIPES-->\n{card_html}',
            1
        )

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(index_content)


def main():
    data = generate_recette_via_ai()
    image_path = generate_image(data["titre"])
    html = generate_html_from_template(data, image_path)
    article_file = save_article(html, data["titre"])
    update_index(data["titre"], data["description"], image_path, article_file)
    print(f"✅ Recette publiée : {article_file}")


if __name__ == "__main__":
    main()
