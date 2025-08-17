#!/usr/bin/env python3
import os
import datetime
from pathlib import Path
from openai import OpenAI
import base64

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
    die("OPENAI_API_KEY manquant (Secrets GitHub > Actions).")
client = OpenAI(api_key=api_key)




def generate_recette_via_ai():
    """Demande à l’IA de générer une recette asiatique facile au format JSON exploitable."""
    prompt = """
    Génère une recette asiatique simple en français, sous format JSON structuré avec les clés :
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

    Concentre-toi sur des recettes asiatiques faciles (nouilles, riz, poulet, légumes, soupe, curry, etc).
    Donne uniquement du JSON valide, sans texte explicatif.
    """
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.7,
        max_output_tokens=800
    )
    import json
    return json.loads(response.output_text)


def generate_image(titre):
    """Génère une image réaliste de la recette avec couverts + baguettes."""
    prompt = f"Photo réaliste d'un plat asiatique : {titre}, servi dans une belle assiette, avec des baguettes élégantes et des couverts modernes, style photo culinaire professionnelle."
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="512x512"  # plus stable que 768x768
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
    """Met à jour l’index.html pour ajouter la nouvelle recette en vignette."""
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index_content = f.read()

    card_html = f"""
    <article class="card">
      <a href="articles/{os.path.basename(article_file)}">
        <img src="{image}" alt="{titre}" />
        <h2>{titre}</h2>
        <p>{desc}</p>
      </a>
    </article>
    """

    if "<!--RECIPES-->" in index_content:
        index_content = index_content.replace("<!--RECIPES-->", card_html + "\n<!--RECIPES-->")
    else:
        index_content += "\n" + card_html

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
