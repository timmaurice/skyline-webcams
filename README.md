# SkylineWebcams for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
![GitHub release (latest by date)](https://img.shields.io/github/v/release/timmaurice/skyline-webcams?style=flat-square)
[![GH-downloads](https://img.shields.io/github/downloads/timmaurice/skyline-webcams/total?style=flat-square)](https://github.com/timmaurice/skyline-webcams/releases)
[![GH-last-commit](https://img.shields.io/github/last-commit/timmaurice/skyline-webcams.svg?style=flat-square)](https://github.com/timmaurice/skyline-webcams/commits/master)
[![GH-code-size](https://img.shields.io/github/languages/code-size/timmaurice/skyline-webcams.svg?style=flat-square)](https://github.com/timmaurice/skyline-webcams)
![GitHub](https://img.shields.io/github/license/timmaurice/skyline-webcams?style=flat-square)

View [SkylineWebcams](https://www.skylinewebcams.com/) streams as native camera entities in Home Assistant.

## Features

- **Webcam Discovery**: Browse and find webcams by continent, country, and location.
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
4.  You have two options: **Browse** or **Manual URL**.

### Browse

1.  Select **Browse**.
2.  Choose your preferred language.
3.  Select a continent.
4.  Select a country.
5.  Browse through the locations and select a webcam.

### Manual URL

1.  Select **Manual URL**.
2.  Enter the full URL of the webcam you want to add.
    - Example: `https://www.skylinewebcams.com/en/webcam/ellada/ionian-islands/corfu/acharavi-beach.html`

## Created Sensors

| Sensor | Description | Attributes | Example Value |
| :----- | :---------- | :--------- | :------------ |
| `camera` | The main camera entity | `description` | Acharavi Beach |
| | | `country` | Greece |
| | | `region` | Ionian Islands |
| | | `place` | Corfu |
| | | `source` | `https://www.skylinewebcams.com/..` |

## Contributions

Contributions are welcome! If you find a bug or have a feature request, please open an issue on the GitHub repository.

## Disclaimer

This integration is not affiliated with or endorsed by SkylineWebcams. It is a community project.

For further assistance or to [report issues](https://github.com/timmaurice/skyline-webcams/issues), please visit the [GitHub repository](https://github.com/timmaurice/skyline-webcams).

![Star History Chart](https://api.star-history.com/svg?repos=timmaurice/skyline-webcams&type=Date)

## ☕ Support My Work

[<img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" height="30" />](https://www.buymeacoffee.com/timmaurice)
