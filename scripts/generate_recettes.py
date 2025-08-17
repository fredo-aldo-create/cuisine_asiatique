#!/usr/bin/env python3
import os
import re
from datetime import datetime, timezone

INDEX_FILE = "index.html"
ARTICLES_DIR = "articles"
IMAGES_DIR = "images"

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

def update_index(titre, desc, image, article_file):
    """Injecte une carte au format INFO-RÉVEIL entre <!-- FEED:start --> et <!-- FEED:end -->, en haut, sans écraser l’existant."""
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

    # Carte EXACTEMENT comme sur le site d’infos
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

    # Injection + déduplication
    def inject(feed_block: str) -> str:
        feed_block = re.sub(
            rf'\s*<!-- card-[^-]+? -->\s*<article class="card">[\s\S]*?href="{re.escape(href)}"[\s\S]*?</article>',
            "", feed_block, flags=re.I
        )
        feed_block = re.sub(r"(<!-- FEED:start -->)", r"\1\n" + card_html, feed_block, count=1, flags=re.S)
        return feed_block

    idx_html = re.sub(r"<!-- FEED:start -->[\s\S]*?<!-- FEED:end -->",
                      lambda m: inject(m.group(0)), idx_html, count=1, flags=re.S)

    # Horodatage
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
    idx_html = idx_html + f"\n<!-- automated-build {stamp} -->\n"

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(idx_html)

# ============ Exemple de génération (à adapter selon ton flux) ============

def generate_recipe(title, description, content, image_filename):
    """Crée un fichier article HTML + met à jour index."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    article_filename = f"{date_str}-{slug}.html"
    article_path = os.path.join(ARTICLES_DIR, article_filename)

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
</head>
<body>
  <h1>{title}</h1>
  <img src="../images/{os.path.basename(image_filename)}" alt="{title}">
  <p>{description}</p>
  <div>{content}</div>
</body>
</html>"""

    os.makedirs(ARTICLES_DIR, exist_ok=True)
    with open(article_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    update_index(title, description, image_filename, article_path)

# Exemple d’utilisation
if __name__ == "__main__":
    generate_recipe(
        "Poulet sauté aux légumes à la sauce soja",
        "Un plat savoureux de poulet tendre accompagné de légumes croquants, le tout relevé d'une délicieuse sauce soja.",
        "<p>Étape 1 : Couper le poulet... etc.</p>",
        "images/poulet.jpg"
    )
   
