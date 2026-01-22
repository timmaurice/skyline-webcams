# SkylineWebcams for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

View [SkylineWebcams](https://www.skylinewebcams.com/) streams as native camera entities in Home Assistant.

## Features

- **Dynamic Stream Extraction**: Automatically finds the current live stream URL.
- **Token Management**: Handles authentication tokens for streams.
- **Native Streaming**: Uses Home Assistant's `stream` component for efficient playback and snapshot generation.

## Installation

### Method 1: HACS (Recommended)

1.  Open HACS.
2.  Click on **Integrations**.
3.  Click the menu icon (dots) in the top right and select **Custom repositories**.
4.  Add the URL of this repository.
5.  Select **Integration** as the category.
6.  Click **Add**.
7.  Find **SkylineWebcams** in the list and install it.
8.  Restart Home Assistant.

### Method 2: Manual

1.  Download the `custom_components/skylinewebcams` folder.
2.  Copy it to your Home Assistant `config/custom_components/` directory.
3.  Restart Home Assistant.

## Configuration

1.  Go to **Settings** > **Devices & Services** > **Integrations**.
2.  Click **Add Integration**.
3.  Search for **SkylineWebcams**.
4.  Enter the URL of the webcam you want to add.
    - Example: `https://www.skylinewebcams.com/en/webcam/ellada/ionian-islands/corfu/acharavi-beach.html`

## Disclaimer

This integration is not affiliated with or endorsed by SkylineWebcams. It is a community project.
