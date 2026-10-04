"""Constants for the SkylineWebcams integration."""

DOMAIN = "skylinewebcams"
CONF_URL = "url"

# How long to wait before looking at the page of a webcam that is offline again.
# An offline webcam is not an outage to recover from in seconds: it is switched
# off on the site's side, and it usually stays that way for hours. Looking every
# few minutes would only scrape a page that keeps saying the same thing.
OFFLINE_RETRY_SECONDS = 15 * 60
