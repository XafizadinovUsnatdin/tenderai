import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


OUTPUT_DIR = Path("audit_output")
OUTPUT_DIR.mkdir(exist_ok=True)


TARGET_URLS = [
    # Keyingi test uchun shu joyga saytlar qo'shiladi
    "https://etender.uzex.uz/",
    "https://etender.uzex.uz/lots/1/0",
]


def safe_filename(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "home"
    return f"{parsed.netloc}_{path}"


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


async def audit_page(page_url: str, wait_seconds: int = 60):
    print(f"\n🔎 Opening: {page_url}")

    network_logs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        )

        async def on_response(response):
            request = response.request
            url = response.url
            content_type = response.headers.get("content-type", "")

            is_interesting = (
                "api" in url.lower()
                or "json" in content_type.lower()
                or "file" in url.lower()
                or "download" in url.lower()
                or "lot" in url.lower()
                or "tender" in url.lower()
                or "common" in url.lower()
                or "lib" in url.lower()
                or "search" in url.lower()
            )

            if not is_interesting:
                return

            item = {
                "url": url,
                "method": request.method,
                "status": response.status,
                "content_type": content_type,
                "post_data": request.post_data,
                "response_preview": None,
            }

            try:
                if "json" in content_type.lower():
                    body = await response.text()
                    item["response_preview"] = body[:3000]
            except Exception as exc:
                item["response_preview"] = f"Could not read body: {exc}"

            network_logs.append(item)

            print("\n🌐 INTERESTING REQUEST")
            print("METHOD:", item["method"])
            print("STATUS:", item["status"])
            print("URL:", item["url"])
            if item["post_data"]:
                print("POST DATA:", item["post_data"][:700])

        page.on("response", on_response)

        try:
            await page.goto(page_url, timeout=180_000)

            # networkidle ba'zi saytlar uchun osilib qoladi.
            # Shuning uchun domcontentloaded + manual wait ishlatamiz.
            #await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=120_000)
            except Exception:
                print("⚠️ domcontentloaded kutish vaqti tugadi, lekin davom etamiz...")
            
            await page.wait_for_timeout(10_000)

            print("\nBrauzer ochildi.")
            print("Endi qo'lda qidiruv qiling, filter bosing, lot detail oching.")
            print(f"{wait_seconds} soniya davomida network log yoziladi.\n")
            await asyncio.to_thread(input, "Tugatgach ENTER bosing: ")
           

            html = await page.content()
            text = extract_visible_text(html)

            file_prefix = safe_filename(page_url)

            (OUTPUT_DIR / f"{file_prefix}.html").write_text(
                html,
                encoding="utf-8",
            )

            (OUTPUT_DIR / f"{file_prefix}.txt").write_text(
                text,
                encoding="utf-8",
            )

            (OUTPUT_DIR / f"{file_prefix}_network.json").write_text(
                json.dumps(network_logs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            await page.screenshot(
                path=str(OUTPUT_DIR / f"{file_prefix}.png"),
                full_page=True,
            )

            print("\n✅ Saved:")
            print(OUTPUT_DIR / f"{file_prefix}_network.json")

        except Exception as exc:
            print(f"❌ Error: {exc}")

        finally:
            await browser.close()


async def main():
    for url in TARGET_URLS:
        await audit_page(url, wait_seconds=60)


if __name__ == "__main__":
    asyncio.run(main())