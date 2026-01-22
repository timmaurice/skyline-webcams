import asyncio
import aiohttp
import re

URL = "https://www.skylinewebcams.com/en/webcam/ellada/ionian-islands/corfu/acharavi-beach.html"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


async def main():
    async with aiohttp.ClientSession() as session:
        # 1. Get Token/URL and Cookies
        print(f"Fetching page: {URL}")
        headers = {"User-Agent": UA}
        async with session.get(URL, headers=headers) as resp:
            text = await resp.text()
            cookies = session.cookie_jar.filter_cookies(URL)
            print(f"Cookies found: {list(cookies.keys())}")

        match = re.search(r"source\s*:\s*['\"](livee?\.m3u8\?a=[^'\"]+)['\"]", text)
        if not match:
            print("Failed to extract stream URL from page")
            return

        original_stream_path = match.group(1)
        token = original_stream_path.split("?")[1]

        urls_to_test = {
            "livee": f"https://hd-auth.skylinewebcams.com/livee.m3u8?{token}",
            "live": f"https://hd-auth.skylinewebcams.com/live.m3u8?{token}",
        }

        for name, stream_url in urls_to_test.items():
            print(f"\n--- Testing {name} ---")
            print(f"URL: {stream_url}")

            # Test A: No Headers, No Cookies
            try:
                print("  [No Headers/Cookies]: ", end="")
                async with session.get(stream_url) as resp:
                    data = await resp.text()
                    first_segment = (
                        data.splitlines()[5] if len(data.splitlines()) > 5 else "N/A"
                    )
                    print(f"Status: {resp.status}, Segment: {first_segment}")
            except Exception as e:
                print(f"Error: {e}")

            # Test C: Full Browser Simulation (Headers + Cookies + Origin)
            try:
                print("  [Full Browser Sim]:   ", end="")

                # Manually construct headers
                full_headers = {
                    "User-Agent": UA,
                    "Referer": "https://www.skylinewebcams.com/",
                    "Origin": "https://www.skylinewebcams.com",
                }

                # Manually pass cookies (since domains differ)
                # PHPSESSID is on .skylinewebcams.com or www?
                # If it's on www, it won't be sent to hd-auth unless we force it.
                # Let's simple formatted string for Cookie header
                # Manually pass cookies
                if cookies:
                    cookie_str = "; ".join(
                        [f"{k}={v.value}" for k, v in cookies.items()]
                    )
                    full_headers["Cookie"] = cookie_str

                async with session.get(stream_url, headers=full_headers) as resp:
                    data = await resp.text()
                    # Check for copyright violation
                    first_lines = data.splitlines()
                    # Look deeper than line 5 just in case
                    is_success = True
                    sample_segment = "N/A"
                    for line in first_lines:
                        if line.startswith("http") and ".ts" in line:
                            sample_segment = line
                            if "copyright" in line or "violation" in line:
                                is_success = False
                            break

                    status_label = (
                        "SUCCESS" if is_success and sample_segment != "N/A" else "FAIL"
                    )
                    print(
                        f"Status: {resp.status} [{status_label}], Segment: {sample_segment}"
                    )
            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
