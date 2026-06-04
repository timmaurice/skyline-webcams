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

### Docker (Development & Testing)

For a quick trial or development, a Docker environment is provided.

1.  Clone this repository.
2.  Run `docker compose up`.
3.  Access Home Assistant at [http://localhost:8123](http://localhost:8123).

The Docker environment comes **pre-configured** with a live webcam (Neuschwanstein Castle) so you can see it in action immediately.

## Configuration

### UI (Recommended)

1.  Go to **Settings** > **Devices & Services** > **Integrations**.
2.  Click **Add Integration**.
3.  Search for **SkylineWebcams**.
4.  You have two options: **Browse** or **Manual URL**.

#### Browse

1.  Select **Browse**.
2.  Choose your preferred language.
3.  Select a continent.
4.  Select a country.
5.  Browse through the locations and select a webcam.

#### Manual URL

1.  Select **Manual URL**.
2.  Enter the full URL of the webcam you want to add.
    - Example: `https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/schloss-neuschwanstein.html`

### YAML

You can also configure cameras directly in your `configuration.yaml`:

```yaml
camera:
  - platform: skylinewebcams
    name: 'Schwangau - Neuschwanstein Castle'
    url: 'https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/schloss-neuschwanstein.html'

  - platform: skylinewebcams
    name: 'New York - Times Square'
    url: 'https://www.skylinewebcams.com/en/webcam/united-states/new-york/new-york/times-square.html'

  - platform: skylinewebcams
    name: 'Venice - St Mark Square'
    url: 'https://www.skylinewebcams.com/en/webcam/italia/veneto/venezia/piazza-san-marco.html'

  - platform: skylinewebcams
    name: 'Rome - Pantheon'
    url: 'https://www.skylinewebcams.com/en/webcam/italia/lazio/roma/pantheon.html'
```

## Created Sensors

| Sensor   | Description            | Attributes    | Example Value                                                                  |
| :------- | :--------------------- | :------------ | :----------------------------------------------------------------------------- |
| `camera` | The main camera entity | `description` | Panoramic view of Schwangau, the Neuschwanstein and the Hohenschwangau Castles |
|          |                        | `country`     | Germany                                                                        |
|          |                        | `region`      | Bavaria                                                                        |
|          |                        | `place`       | Schwangau                                                                      |
|          |                        | `source`      | `https://www.skylinewebcams.com/..`                                            |

### Lovelace Card

This integration includes a dedicated custom Lovelace card: `custom:skyline-webcams-card`.

<img src="https://raw.githubusercontent.com/timmaurice/skyline-webcams/main/image.png" alt="Card Screenshot" width="400" />

#### Card Features

- **Overlay Controls**: Interactive control bar (Play/Pause, Picture-in-Picture, Fullscreen) that fades in smoothly on hover.
- **Viewport Pausing (IntersectionObserver)**: Automatically pauses playback and detaches Hls.js when the card is scrolled out of the viewport or the tab is hidden, optimizing network usage and CPU.
- **Backend LRU Chunk Cache**: The backend proxy uses a thread-safe LRU caching mechanism for `.ts` video chunks, speeding up card startup and reducing upstream server requests when multiple views are active.

#### Card Configuration

| Name                  | Type    | Default      | Description                                                                  |
| :-------------------- | :------ | :----------- | :--------------------------------------------------------------------------- |
| `type`                | string  | **Required** | `custom:skyline-webcams-card`                                                |
| `entity`              | string  | **Required** | The camera entity (e.g., `camera.live_cam_schwangau_neuschwanstein_castle`)  |
| `title`               | string  | `(none)`     | Custom title for the card (falls back to entity friendly name if omitted)    |
| `aspect_ratio`        | string  | `16/9`       | Aspect ratio of the video player container (e.g., `16/9`, `4/3`)             |
| `show_link`           | boolean | `false`      | Show a direct link to the original webcam page on SkylineWebcams             |
| `show_video_controls` | boolean | `true`       | Show the video overlay controls (Play/Pause, Picture-in-Picture, Fullscreen) |

#### Example YAML

```yaml
type: custom:skyline-webcams-card
entity: camera.live_cam_schwangau_neuschwanstein_castle
aspect_ratio: 16/9
show_link: true
```

<details>
<summary>Alternative Generic Card configuration</summary>

<img src="https://raw.githubusercontent.com/timmaurice/skyline-webcams/main/image-generic.png" alt="Card Screenshot Generic" width="400" />

If you prefer not to use the custom card, you can combine Home Assistant's built-in `picture-entity` and `markdown` cards:

```yaml
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
