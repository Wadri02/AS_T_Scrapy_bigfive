"""
Instagram Profile Scraper con Playwright (Python) - v11
Uso: python instagram_scraper.py <username>
Requiere: pip install playwright && playwright install chromium
"""

import asyncio
import json
import sys
import re
import os
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

COOKIES_FILE = "cookies.json"
USERNAME     = sys.argv[1] if len(sys.argv) > 1 else "instagram"
HEADLESS     = False
MAX_POSTS    = 10
MAX_COMMENTS = 4
IMG_DIR      = "imagenes"


def load_cookies(filepath: str) -> list[dict]:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"No se encontró: {filepath}")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    cookies = []
    for c in raw:
        ck = {
            "name":   c.get("name", ""),
            "value":  c.get("value", ""),
            "domain": c.get("domain", ".instagram.com"),
            "path":   c.get("path", "/"),
        }
        exp = c.get("expirationDate") or c.get("expires")
        if exp and isinstance(exp, (int, float)) and exp > 0:
            ck["expires"] = int(exp)
        if ck["name"] and ck["value"]:
            cookies.append(ck)
    print(f"✅ {len(cookies)} cookies cargadas")
    return cookies


async def sleep(s: float):
    await asyncio.sleep(s)

async def dismiss_modals(page):
    for text in ["Not now", "Ahora no", "Not Now", "Cerrar", "Close"]:
        try:
            btn = page.get_by_text(text, exact=True)
            if await btn.count():
                await btn.first.click(timeout=2000)
                await sleep(0.8)
        except Exception:
            pass

async def scroll_to_load_posts(page, needed: int) -> list[str]:
    for _ in range(25):
        links = await page.locator('a[href*="/p/"]').all()
        seen, hrefs = set(), []
        for l in links:
            h = await l.get_attribute("href")
            if h and h not in seen:
                seen.add(h); hrefs.append(h)
        if len(hrefs) >= needed:
            return hrefs
        await page.evaluate("window.scrollBy(0, 900)")
        await sleep(1.5)
    links = await page.locator('a[href*="/p/"]').all()
    seen, hrefs = set(), []
    for l in links:
        h = await l.get_attribute("href")
        if h and h not in seen:
            seen.add(h); hrefs.append(h)
    return hrefs

def download_image(url: str, filepath: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.instagram.com/"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            with open(filepath, "wb") as f:
                f.write(resp.read())
        return True
    except Exception as e:
        print(f"      ⚠️  Error descargando imagen: {e}")
        return False


async def extract_profile(page) -> dict:
    data = {"bio": "", "followers": "", "following": ""}
    try:
        el = page.locator('a[href$="/followers/"]').first
        if await el.count():
            text = (await el.inner_text()).strip()
            num = re.split(r'\s+(seguidor|follower)', text, flags=re.I)[0].strip()
            data["followers"] = num or text
    except Exception:
        pass
    try:
        el = page.locator('a[href$="/following/"]').first
        if await el.count():
            text = (await el.inner_text()).strip()
            num = re.split(r'\s+(seguido|following)', text, flags=re.I)[0].strip()
            data["following"] = num or text
    except Exception:
        pass
    try:
        els = await page.locator('header section div span[dir="auto"]').all()
        candidates = [(await e.inner_text()).strip() for e in els]
        candidates = [c for c in candidates if len(c) > 5]
        if candidates:
            data["bio"] = max(candidates, key=len)
    except Exception:
        pass
    return data


async def extract_date(post_page) -> str:
    try:
        await post_page.wait_for_selector("time[datetime]", timeout=8000)
        el = post_page.locator("time[datetime]").first
        return (await el.get_attribute("datetime")) or ""
    except Exception:
        pass
    return ""


async def extract_location(post_page) -> str:
    """
    Ubicación: a[href*="/explore/locations/"] con texto visible.
    Confirmado: "Seoul, South Korea" en este selector.
    """
    try:
        el = post_page.locator('a[href*="/explore/locations/"]').first
        if await el.count():
            text = (await el.inner_text()).strip()
            # Evitar el link genérico "Ubicaciones" del menú
            if text and text.lower() not in ("ubicaciones", "locations", "explore"):
                return text
    except Exception:
        pass
    return ""


async def extract_caption_and_comments(post_page, max_comments: int) -> tuple[str, list[dict]]:
    """
    Extrae el caption del autor y los comentarios.

    Estructura confirmada por debug:
    - CAPTION: span con clases 'x193iq5w xeuugli x13faqbe x1vvkbs xt0psk2 x1i0vuye'
               Es un span completamente separado del span._ap3a
    - COMENTARIOS: span._ap3a sube ~9 niveles → contenedor con 4 span[dir=auto]
               [0]=outer autor, [1]=_ap3a autor, [2]=timestamp, [3]=texto comentario
    """
    caption  = ""
    comments = []

    try:
        await post_page.wait_for_selector("span._ap3a", timeout=8000)
    except Exception:
        return caption, comments

    await sleep(1.5)

    try:
        # CAPTION: clase exacta confirmada por debug
        # La clase x126k92a es única del caption (no aparece en timestamps ni acciones)
        # Clases completas: x193iq5w xeuugli x13faqbe x1vvkbs xt0psk2 x1i0vuye xvs91rp xo1l8bm x5n08af x126k92a
        cap_el = post_page.locator('span.x126k92a').first
        if await cap_el.count():
            caption = (await cap_el.inner_text()).strip()
    except Exception:
        pass

    try:
        # COMENTARIOS: mismo método confirmado (nivel 9, span[dir=auto][3])
        results = await post_page.evaluate("""() => {
            const out = [];
            const allAp3a = document.querySelectorAll('span._ap3a');

            for (const ap3a of allAp3a) {
                let container = ap3a;
                let level = 0;

                while (container.parentElement && level < 15) {
                    container = container.parentElement;
                    level++;
                    const spans = container.querySelectorAll('span[dir="auto"]');

                    if (level <= 10 && spans.length >= 4) {
                        const author = spans[1] ? spans[1].innerText.trim() : '';
                        const text   = spans[3] ? spans[3].innerText.trim() : '';
                        if (author && text) {
                            out.push({ author, text });
                        }
                        break;
                    }
                }
            }

            // Deduplicar
            const seen = new Set();
            return out.filter(c => {
                const key = c.author + '|' + c.text;
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
            });
        }""")

        skip = {"responder", "reply", "me gusta", "like",
                "ver traducción", "view translation",
                "ver respuestas", "view replies"}

        for item in results:
            if len(comments) >= max_comments:
                break
            author = item.get("author", "").strip()
            text   = item.get("text", "").strip()
            if not author or not text:
                continue
            if text.lower() in skip:
                continue
            if re.match(r'^\d+\s*(sem|h|d|w|min|s)\b', text.lower()):
                continue
            comments.append({"author": author, "text": text})

    except Exception as e:
        print(f"      ⚠️  Error comentarios: {e}")

    return caption, comments


async def extract_image(post_page) -> str:
    try:
        await post_page.wait_for_selector("._aagv img", timeout=5000)
        img = post_page.locator("._aagv img").first
        if await img.count():
            src = (await img.get_attribute("src")) or ""
            if src:
                return src
    except Exception:
        pass
    try:
        imgs = await post_page.locator("img[src*='fbcdn']").all()
        for img in imgs:
            alt = (await img.get_attribute("alt")) or ""
            src = (await img.get_attribute("src")) or ""
            if src and len(alt) > 15:
                return src
    except Exception:
        pass
    return ""


async def scrape_post(context, href: str, idx: int) -> dict:
    url     = f"https://www.instagram.com{href}"
    post_id = href.strip("/").split("/")[-1]
    print(f"\n  📸 Post {idx}: {url}")

    post = {
        "url":      url,
        "date":     "",
        "location": "",
        "caption":  "",
        "image":    "",
        "comments": [],
    }

    post_page = await context.new_page()
    try:
        await post_page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await sleep(2)
        await dismiss_modals(post_page)

        post["date"]     = await extract_date(post_page)
        post["location"] = await extract_location(post_page)

        caption, comments = await extract_caption_and_comments(post_page, MAX_COMMENTS)
        post["caption"]  = caption
        post["comments"] = comments

        img_url = await extract_image(post_page)
        if img_url:
            os.makedirs(IMG_DIR, exist_ok=True)
            img_path = os.path.join(IMG_DIR, f"{post_id}.jpg")
            ok = download_image(img_url, img_path)
            post["image"] = img_path if ok else ""
            img_status = f"✅ {img_path}" if ok else "❌ error"
        else:
            img_status = "❌ no encontrada"

        print(f"    📅 Fecha     : {post['date']}")
        print(f"    📍 Ubicación : {post['location']}")
        print(f"    📝 Caption   : {post['caption'][:80] if post['caption'] else '(vacío)'}")
        print(f"    🖼️  Imagen    : {img_status}")
        print(f"    💬 Comentarios ({len(post['comments'])}):")
        for i, c in enumerate(post["comments"], 1):
            print(f"       [{i}] @{c['author']}: {c['text'][:80]}")

    except Exception as e:
        print(f"    ❌ Error: {e}")
    finally:
        await post_page.close()

    return post


async def scrape_profile(username: str, cookies: list[dict]) -> dict:
    result = {
        "username":  username,
        "bio":       "",
        "followers": "",
        "following": "",
        "posts":     [],
    }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="es-ES",
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        try:
            print(f"\n🔍 Navegando a @{username} …")
            await page.goto(
                f"https://www.instagram.com/{username}/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await sleep(4)
            await dismiss_modals(page)
            await sleep(1)

            if "login" in page.url or "accounts" in page.url:
                print("❌ Redirigido a login — cookies expiradas.")
                await browser.close()
                return result

            print("📋 Extrayendo datos del perfil …")
            profile = await extract_profile(page)
            result.update({
                "bio":       profile["bio"],
                "followers": profile["followers"],
                "following": profile["following"],
            })
            try:
                result["username"] = (await page.locator("header h2, header h1").first.inner_text()).strip()
            except Exception:
                pass

            print(f"  👤 Username  : {result['username']}")
            print(f"  📝 Bio       : {result['bio'][:100]}")
            print(f"  👥 Seguidores: {result['followers']}")
            print(f"  👁️  Seguidos  : {result['following']}")

            print(f"\n🖼️  Buscando {MAX_POSTS} publicaciones …")
            hrefs = await scroll_to_load_posts(page, MAX_POSTS)
            hrefs = hrefs[:MAX_POSTS]
            print(f"  Encontrados: {len(hrefs)} posts")

            for idx, href in enumerate(hrefs, 1):
                post = await scrape_post(context, href, idx)
                result["posts"].append(post)

        except Exception as e:
            print(f"\n❌ Error general: {e}")
        finally:
            await browser.close()

    return result


async def main():
    print(f"🚀 Instagram Scraper v11 — @{USERNAME}")
    cookies = load_cookies(COOKIES_FILE)
    data = await scrape_profile(USERNAME, cookies)

    out = f"{USERNAME}_instagram.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Guardado en: {out}")
    print(f"\n📊 RESUMEN FINAL:")
    print(f"  👤 {data['username']}")
    print(f"  📝 {data['bio'][:80]}")
    print(f"  👥 Seguidores : {data['followers']}")
    print(f"  👁️  Seguidos   : {data['following']}")
    print(f"  🖼️  Posts      : {len(data['posts'])}")
    imgs = sum(1 for p in data["posts"] if p.get("image"))
    print(f"  📷 Imágenes   : {imgs}/{len(data['posts'])} en /{IMG_DIR}")
    total_c = sum(len(p["comments"]) for p in data["posts"])
    print(f"  💬 Comentarios: {total_c}")

if __name__ == "__main__":
    asyncio.run(main())