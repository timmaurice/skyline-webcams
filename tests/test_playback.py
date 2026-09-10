from unittest.mock import AsyncMock
import asyncio
import aiohttp
import re
import pytest
import logging
from unittest.mock import patch


_LOGGER = logging.getLogger(__name__)

URL = "https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/schloss-neuschwanstein.html"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@pytest.fixture
def mock_aiohttp_session_playback(mocker):
    """Fixture to mock aiohttp.ClientSession for offline testing of stream playback."""
    # Mock for the initial page fetch
    mock_response_page = mocker.AsyncMock(spec=aiohttp.ClientResponse)
    mock_response_page.status = 200
    mock_response_page.text.return_value = """
        <html>
            <body>
                <script>
                    var player = new Clappr.Player({
                        source: 'livee.m3u8?a=some_token_here',
                    });
                </script>
            </body>
        </html>
    """
    mock_response_page.cookie_jar = mocker.Mock()
    mock_response_page.cookie_jar.filter_cookies.return_value = (
        {}
    )  # No cookies for mock
    mock_response_page.__aenter__.return_value = mock_response_page
    mock_response_page.__aexit__.return_value = None

    # Mock for the stream URL fetches
    mock_response_stream = mocker.AsyncMock(spec=aiohttp.ClientResponse)
    mock_response_stream.status = 200
    mock_response_stream.text.return_value = """
        #EXTM3U
        #EXT-X-VERSION:3
        #EXT-X-TARGETDURATION:10
        #EXT-X-MEDIA-SEQUENCE:0
        #EXTINF:10.000,
        http://example.com/segment1.ts
        #EXTINF:10.000,
        http://example.com/segment2.ts
    """
    mock_response_stream.__aenter__.return_value = mock_response_stream
    mock_response_stream.__aexit__.return_value = None

    mock_session_instance = mocker.AsyncMock(spec=aiohttp.ClientSession)
    mock_session_instance.__aenter__.return_value = mock_session_instance
    mock_session_instance.__aexit__.return_value = None

    mock_session_instance.get.side_effect = [
        mock_response_page,
        mock_response_stream,
        mock_response_stream,
        mock_response_stream,
        mock_response_stream,
    ]
    # Patch ClientSession
    mocker.patch("aiohttp.ClientSession", return_value=mock_session_instance)
    return mock_session_instance


@pytest.mark.asyncio
async def test_stream_playback(mock_aiohttp_session_playback):
    """Test fetching stream URL and verifying playback with different headers."""
    async with aiohttp.ClientSession() as session:
        # 1. Get Token/URL and Cookies
        _LOGGER.info(f"Fetching page: {URL}")
        headers = {"User-Agent": UA}
        async with session.get(URL, headers=headers) as resp:
            assert (
                resp.status == 200
            ), f"Failed to fetch page: {URL}, Status: {resp.status}"
            text = await resp.text()
            cookies = session.cookie_jar.filter_cookies(URL)
            _LOGGER.debug(f"Cookies found: {list(cookies.keys())}")

        match = re.search(r'source\s*:\s*["\'](livee?\.m3u8\?a=[^"\']+)["\']', text)
        assert match, "Failed to extract stream URL from page"

        original_stream_path = match.group(1)
        token = original_stream_path.split("?")[1]

        urls_to_test = {
            "livee": f"https://hd-auth.skylinewebcams.com/livee.m3u8?{token}",
            "live": f"https://hd-auth.skylinewebcams.com/live.m3u8?{token}",
        }

        for name, stream_url in urls_to_test.items():
            _LOGGER.info(f"--- Testing {name} ---")
            _LOGGER.info(f"URL: {stream_url}")

            # Test A: No Headers, No Cookies
            _LOGGER.info("  [No Headers/Cookies]: ")
            async with session.get(stream_url) as resp:
                assert (
                    resp.status == 200
                ), f"[{name}] Stream (no headers) returned non-200 status: {resp.status}"
                data = await resp.text()
                first_segment = (
                    data.splitlines()[6] if len(data.splitlines()) > 6 else None
                )
                assert first_segment is not None and first_segment.strip().startswith(
                    "http"
                ), f"[{name}] Did not find a valid stream segment (no headers)."

            # Test C: Full Browser Simulation (Headers + Cookies + Origin)
            _LOGGER.info("  [Full Browser Sim]:   ")

            # Manually construct headers
            full_headers = {
                "User-Agent": UA,
                "Referer": "https://www.skylinewebcams.com/",
                "Origin": "https://www.skylinewebcams.com",
            }

            if cookies:  # This will be empty due to mock
                cookie_str = "; ".join([f"{k}={v.value}" for k, v in cookies.items()])
                full_headers["Cookie"] = cookie_str

            async with session.get(stream_url, headers=full_headers) as resp:
                assert (
                    resp.status == 200
                ), f"[{name}] Stream (full headers) returned non-200 status: {resp.status}"
                data = await resp.text()
                is_success = False
                sample_segment = None
                for line in data.splitlines():
                    stripped_line = line.strip()
                    if stripped_line.startswith("http") and ".ts" in stripped_line:
                        sample_segment = stripped_line
                        if (
                            "copyright" not in stripped_line
                            and "violation" not in stripped_line
                        ):
                            is_success = True
                        break

                assert (
                    is_success
                ), f"[{name}] Stream (full headers) contained copyright/violation or no valid segment."
                assert sample_segment is not None and sample_segment.strip().startswith(
                    "http"
                ), f"[{name}] Did not find a valid stream segment (full headers)."
