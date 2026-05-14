import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


OUTPUT_DIR = Path("audit_output")
OUTPUT_DIR.mkdir(exist_ok=True)

TARGET_URL = "https://xarid.uzex.uz/completed-deals/shop/shop"


def safe_filename(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "home"
    return f"{parsed.netloc}_{path}"


async def main():
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
                "xarid-api" in url.lower()
                or "application/json" in content_type.lower()
                or "/Common/" in url
                or "/Lib/" in url
                or "/Info/" in url
            )

            if not is_interesting:
                return

            log_item = {
                "url": url,
                "method": request.method,
                "status": response.status,
                "content_type": content_type,
                "post_data": request.post_data,
                "response_preview": None,
            }

            try:
                if "application/json" in content_type.lower():
                    body = await response.text()
                    log_item["response_preview"] = body[:3000]
            except Exception as exc:
                log_item["response_preview"] = f"Could not read body: {exc}"

            network_logs.append(log_item)

            print("\n🌐 API FOUND")
            print("METHOD:", log_item["method"])
            print("STATUS:", log_item["status"])
            print("URL:", log_item["url"])
            if log_item["post_data"]:
                print("POST DATA:", log_item["post_data"][:500])

        page.on("response", on_response)

        print(f"Opening: {TARGET_URL}")
        await page.goto(TARGET_URL, timeout=60_000)
        await page.wait_for_load_state("networkidle", timeout=30_000)

        print("\nBrauzer ochildi.")
        print("Endi brauzerda qo‘lda qidiruv qiling:")
        print("Masalan: TP-Link, printer, konditsioner")
        print("Filterlarni bosib ko‘ring.")
        print("60 soniya kutaman va hamma API requestlarni yozib olaman.\n")

        await page.wait_for_timeout(60_000)

        file_prefix = safe_filename(TARGET_URL)

        (OUTPUT_DIR / f"{file_prefix}_interactive_network.json").write_text(
            json.dumps(network_logs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        html = await page.content()

        (OUTPUT_DIR / f"{file_prefix}_after_search.html").write_text(
            html,
            encoding="utf-8",
        )

        await page.screenshot(
            path=str(OUTPUT_DIR / f"{file_prefix}_after_search.png"),
            full_page=True,
        )

        print("\n✅ Saqlandi:")
        print(OUTPUT_DIR / f"{file_prefix}_interactive_network.json")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())