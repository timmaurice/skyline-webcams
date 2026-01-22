import asyncio
import aiohttp
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

URL = "https://www.skylinewebcams.com/en/webcam/ellada/ionian-islands/corfu/acharavi-beach.html"


async def fetch_stream_url(url):
    print(f"Fetching {url}...")
    async with aiohttp.ClientSession() as session:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 1. Fetch Page
        async with session.get(url, headers=headers) as response:
            text = await response.text()
            print(f"Page fetched. Status: {response.status}")

            # 2. Extract Token
            match = re.search(r"source\s*:\s*['\"](livee?\.m3u8\?a=[^'\"]+)['\"]", text)
            if match:
                stream_path = match.group(1)
                # Force replace livee -> live
                stream_path = stream_path.replace("livee", "live")

                full_stream_url = f"https://hd-auth.skylinewebcams.com/{stream_path}"
                print(f"Found stream URL: {full_stream_url}")

                # 3. Verify Stream
                print("Verifying stream availability...")
                async with session.head(full_stream_url) as stream_resp:
                    print(f"Stream Status: {stream_resp.status}")
                    print(f"Stream Headers: {stream_resp.headers}")
                    if stream_resp.status == 200:
                        print("SUCCESS: Stream is accessible.")
                    else:
                        print("FAILURE: Stream returned non-200 status.")
            else:
                print("FAILURE: Could not find stream source pattern in page.")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(fetch_stream_url(URL))
