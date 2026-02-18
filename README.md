# SkylineWebcams for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
![GitHub release (latest by date)](https://img.shields.io/github/v/release/timmaurice/skyline-webcams?style=flat-square)
[![GH-downloads](https://img.shields.io/github/downloads/timmaurice/skyline-webcams/total?style=flat-square)](https://github.com/timmaurice/skyline-webcams/releases)
[![GH-last-commit](https://img.shields.io/github/last-commit/timmaurice/skyline-webcams.svg?style=flat-square)](https://github.com/timmaurice/skyline-webcams/commits/master)
[![GH-code-size](https://img.shields.io/github/languages/code-size/timmaurice/skyline-webcams.svg?style=flat-square)](https://github.com/timmaurice/skyline-webcams)
![GitHub](https://img.shields.io/github/license/timmaurice/skyline-webcams?style=flat-square)

View [SkylineWebcams](https://www.skylinewebcams.com/) streams as native camera entities in Home Assistant.

<img src="https://cdn.brandfetch.io/id2mczdJ_1/w/1500/h/500/idVkBsrVjZ.jpeg?c=1bxid64Mup7aczewSAYMX&t=1764739803892" title="+5000 Live Cams">

## Features

- **Webcam Discovery**: Browse and find webcams by continent, country, and location.
- **Dynamic Stream Extraction**: Automatically finds the current live stream URL.
- **Token Management**: Handles authentication tokens for streams.
- **Native Streaming**: Uses Home Assistant's `stream` component for efficient playback and snapshot generation.

## Installation

### HACS (Recommended)

This card is available in the [Home Assistant Community Store (HACS)](https://hacs.xyz/).

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=timmaurice&repository=skyline-webcams&category=integration" target="_blank" rel="noreferrer noopener"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open your Home Assistant instance and open a repository inside the Home Assistant Community Store." /></a>

<details>
<summary>Manual Installation</summary>

1.  Download the `custom_components/skylinewebcams` folder.
2.  Copy it to your Home Assistant `config/custom_components/` directory.
3.  Restart Home Assistant.
</details>

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
    - Example: `https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/schloss-neuschwanstein.html`

## Created Sensors

| Sensor   | Description            | Attributes    | Example Value                                                                  |
| :------- | :--------------------- | :------------ | :----------------------------------------------------------------------------- |
| `camera` | The main camera entity | `description` | Panoramic view of Schwangau, the Neuschwanstein and the Hohenschwangau Castles |
|          |                        | `country`     | Germany                                                                        |
|          |                        | `region`      | Bavaria                                                                        |
|          |                        | `place`       | Schwangau                                                                      |
|          |                        | `source`      | `https://www.skylinewebcams.com/..`                                            |

### Card example

<img src="https://raw.githubusercontent.com/timmaurice/skyline-webcams/main/image.png" alt="Card Screenshot" />

<details>
<summary>Code</summary>

```
type: picture-entity
entity: camera.live_cam_schwangau_neuschwanstein_castle
camera_image: camera.live_cam_schwangau_neuschwanstein_castle
camera_view: live
fit_mode: contain
show_name: false
show_state: false

type: markdown
content: >-

## 📍 **{{ state_attr('camera.live_cam_schwangau_neuschwanstein_castle', 'friendly_name') }}**

_{{ state_attr('camera.live_cam_schwangau_neuschwanstein_castle', 'description') }}_

**🌍 Country:** {{ state_attr('camera.live_cam_schwangau_neuschwanstein_castle', 'country') }}

**📌 Region:** {{ state_attr('camera.live_cam_schwangau_neuschwanstein_castle', 'region') }}

**📍 Place:** {{ state_attr('camera.live_cam_schwangau_neuschwanstein_castle', 'place') }}

[🔗 View live webcam]({{ state_attr('camera.live_cam_schwangau_neuschwanstein_castle', 'source') }})
text_only: true

```

</details>

## Contributions

Contributions are welcome! If you find a bug or have a feature request, please open an issue on the GitHub repository.

## Disclaimer

This integration is not affiliated with or endorsed by SkylineWebcams. It is a community project.

For further assistance or to [report issues](https://github.com/timmaurice/skyline-webcams/issues), please visit the [GitHub repository](https://github.com/timmaurice/skyline-webcams).

![Star History Chart](https://api.star-history.com/svg?repos=timmaurice/skyline-webcams&type=Date)

## ☕ Support My Work

[<img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" height="30" />](https://www.buymeacoffee.com/timmaurice)
