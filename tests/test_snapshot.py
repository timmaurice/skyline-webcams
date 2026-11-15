"""Tests for the still image taken from the stream with ffmpeg.

The stream host checks the Referer. ha-ffmpeg puts `extra_cmd` after `-i`, so
headers passed there are output options and never reach upstream. They have to
be input options, ahead of `-i`. The argv is built by ha-ffmpeg itself here, so
the test checks the order ffmpeg really gets.
"""

from unittest.mock import AsyncMock, patch

from haffmpeg.tools import ImageFrame

from custom_components.skylinewebcams.camera import SkylineWebcamsCamera

UPSTREAM = "https://hd-auth.skylinewebcams.com/live.m3u8?a=token"


async def test_a_snapshot_sends_the_referer_upstream(hass):
    camera = SkylineWebcamsCamera(
        hass=hass,
        url="https://www.skylinewebcams.com/en/webcam/test.html",
        name="Test Cam",
        unique_id="test",
        entry_id="cam1",
    )

    with (
        patch.object(
            camera, "get_fresh_stream_url", AsyncMock(return_value=UPSTREAM)
        ) as fresh,
        patch(
            "custom_components.skylinewebcams.camera.async_get_image",
            AsyncMock(return_value=b"jpeg"),
        ) as get_image,
    ):
        assert await camera.async_camera_image() == b"jpeg"

    # Only one page read per snapshot: the fresh URL call is cached anyway.
    fresh.assert_awaited_once()

    ffmpeg = ImageFrame("ffmpeg")
    ffmpeg._generate_ffmpeg_cmd(
        ["-an"],
        get_image.await_args.args[1],
        "-",
        get_image.await_args.kwargs.get("extra_cmd"),
    )
    argv = ffmpeg._argv
    assert argv[argv.index("-i") + 1] == UPSTREAM
    assert argv.index("-referer") < argv.index("-i")
    assert argv[argv.index("-referer") + 1] == "https://www.skylinewebcams.com/"
    assert argv.index("-user_agent") < argv.index("-i")
