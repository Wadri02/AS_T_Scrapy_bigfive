"""
Script de DEBUG v6 - encontrar todos los elementos con la clase del caption
"""
import asyncio
import json
import sys
from playwright.async_api import async_playwright

COOKIES_FILE = "cookies.json"
POST_URL     = sys.argv[1] if len(sys.argv) > 1 else ""

def load_cookies(filepath):
    with open(filepath, encoding="utf-8") as f:
        raw = json.load(f)
    cookies = []
    for c in raw:
        ck = {"name": c.get("name",""), "value": c.get("value",""),
              "domain": c.get("domain",".instagram.com"), "path": c.get("path","/")}
        exp = c.get("expirationDate") or c.get("expires")
        if exp and isinstance(exp,(int,float)) and exp > 0:
            ck["expires"] = int(exp)
        if ck["name"] and ck["value"]:
            cookies.append(ck)
    return cookies

async def main():
    cookies = load_cookies(COOKIES_FILE)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="es-ES",
        )
        await context.add_cookies(cookies)
        page = await context.new_page()
        await page.goto(POST_URL, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        result = await page.evaluate("""() => {
            const out = {};

            // 1. Ver TODOS los elementos que contienen "feliz haluwin"
            // y sus clases exactas
            out.captionElement = null;
            const all = document.querySelectorAll('span, div, p');
            for (const el of all) {
                const t = el.innerText ? el.innerText.trim() : '';
                if (t === '🎃 feliz haluwin 🎃') {
                    out.captionElement = {
                        tag: el.tagName,
                        classes: el.className,
                        parentTag: el.parentElement?.tagName,
                        parentClasses: el.parentElement?.className,
                        grandParentTag: el.parentElement?.parentElement?.tagName,
                        grandParentClasses: el.parentElement?.parentElement?.className?.slice(0,60)
                    };
                    break;
                }
            }

            // 2. Ver cuántos elementos tienen la clase x193iq5w y su texto
            const byClass = document.querySelectorAll('span.x193iq5w');
            out.x193iq5wElements = Array.from(byClass).map(el => ({
                text: el.innerText.trim().slice(0, 80),
                classes: el.className.slice(0, 80)
            })).slice(0, 10);

            // 3. El caption está cerca del autor - buscar el contenedor
            // que tiene tanto el username como el caption
            const ap3a = document.querySelectorAll('span._ap3a')[0];
            if (ap3a) {
                let el = ap3a;
                for (let i = 0; i <= 15; i++) {
                    el = el.parentElement;
                    if (!el) break;
                    const t = el.innerText.trim();
                    if (t.includes('feliz haluwin')) {
                        out.captionContainerLevel = i + 1;
                        out.captionContainerText = t.slice(0, 200);
                        out.captionContainerTag = el.tagName;
                        // Buscar el span hijo que tiene SOLO el caption
                        const children = el.querySelectorAll('span, div');
                        const captionChild = Array.from(children).find(c => 
                            c.innerText.trim() === '🎃 feliz haluwin 🎃'
                        );
                        if (captionChild) {
                            out.captionChildClasses = captionChild.className;
                        }
                        break;
                    }
                }
            }

            return out;
        }""")

        print("\n=== ELEMENTO EXACTO DEL CAPTION ===")
        print(json.dumps(result.get("captionElement"), indent=2, ensure_ascii=False))

        print("\n=== TODOS LOS span.x193iq5w ===")
        for el in result.get("x193iq5wElements", []):
            print(f"  [{el['classes'][:60]}]")
            print(f"  texto: {el['text']}")
            print()

        print("\n=== CONTENEDOR QUE TIENE EL CAPTION ===")
        print(f"  nivel: {result.get('captionContainerLevel')}")
        print(f"  tag  : {result.get('captionContainerTag')}")
        print(f"  texto: {result.get('captionContainerText', '')[:150]}")
        print(f"  clases hijo caption: {result.get('captionChildClasses', '')}")

asyncio.run(main())