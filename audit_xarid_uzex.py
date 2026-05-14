import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


OUTPUT_DIR = Path("audit_output")
OUTPUT_DIR.mkdir(exist_ok=True)


TARGET_PAGES = [
    "https://xarid.uzex.uz/",
    "https://xarid.uzex.uz/completed-deals",
    "https://xarid.uzex.uz/completed-deals/shop/shop",
    "https://xarid.uzex.uz/shop/products-list/eshop",
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


async def audit_page(page_url: str):
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
            url = response.url
            content_type = response.headers.get("content-type", "")

            # Bizga asosan API/JSON/XHR so'rovlar kerak
            if (
                "json" in content_type.lower()
                or "api" in url.lower()
                or "Get" in url
                or "get" in url
            ):
                try:
                    status = response.status
                    network_logs.append(
                        {
                            "url": url,
                            "status": status,
                            "content_type": content_type,
                        }
                    )
                    print(f"🌐 {status} | {url}")
                except Exception as exc:
                    print(f"Network log error: {exc}")

        page.on("response", on_response)

        try:
            await page.goto(page_url, timeout=60_000)
            await page.wait_for_load_state("networkidle", timeout=30_000)

            html = await page.content()
            visible_text = extract_visible_text(html)

            file_prefix = safe_filename(page_url)

            (OUTPUT_DIR / f"{file_prefix}.html").write_text(
                html,
                encoding="utf-8",
            )

            (OUTPUT_DIR / f"{file_prefix}.txt").write_text(
                visible_text,
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

            print(f"✅ Saved: {file_prefix}")

        except Exception as exc:
            print(f"❌ Error opening {page_url}: {exc}")

        finally:
            await browser.close()


async def main():
    for url in TARGET_PAGES:
        await audit_page(url)


if __name__ == "__main__":
    asyncio.run(main())