import asyncio
import aiohttp
import re
import logging
import pytest
from unittest.mock import patch


@pytest.fixture
def mock_aiohttp_session(mocker):
    """Fixture to mock aiohttp.ClientSession for offline testing."""
    mock_response_get = mocker.AsyncMock(spec=aiohttp.ClientResponse)
    mock_response_get.status = 200
    mock_response_get.text.return_value = """
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
    mock_response_get.__aenter__.return_value = mock_response_get
    mock_response_get.__aexit__.return_value = None

    mock_response_head = mocker.AsyncMock(spec=aiohttp.ClientResponse)
    mock_response_head.status = 200
    mock_response_head.__aenter__.return_value = mock_response_head
    mock_response_head.__aexit__.return_value = None

    mock_session_instance = mocker.AsyncMock(spec=aiohttp.ClientSession)
    mock_session_instance.__aenter__.return_value = mock_session_instance
    mock_session_instance.__aexit__.return_value = None

    mock_session_instance.get.return_value = mock_response_get
    mock_session_instance.head.return_value = mock_response_head

    mocker.patch("aiohttp.ClientSession", return_value=mock_session_instance)
    return mock_session_instance


# Configure logging
logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

URL = "https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/schloss-neuschwanstein.html"


@pytest.mark.asyncio
async def test_fetch_stream_url(mock_aiohttp_session):
    """Test fetching and parsing a stream URL from a live webcam page."""
    async with aiohttp.ClientSession() as session:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 1. Fetch Page
        async with session.get(URL, headers=headers) as response:
            assert response.status == 200
            text = await response.text()

            # 2. Extract Token
            match = re.search(r"source\s*:\s*['\"](livee?\.m3u8\?a=[^'\"]+)['\"]", text)
            assert match, "Could not find stream source pattern in page"

            stream_path = match.group(1)
            # Force replace livee -> live
            stream_path = stream_path.replace("livee", "live")

            full_stream_url = f"https://hd-auth.skylinewebcams.com/{stream_path}"
            _LOGGER.info(f"Found stream URL: {full_stream_url}")

            # 3. Verify Stream
            async with session.head(full_stream_url) as stream_resp:
                assert stream_resp.status == 200, "Stream returned non-200 status"
