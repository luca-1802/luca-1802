# Profile console

The GitHub profile README is a stack of original animated SVG console panels. Its compact terminal layout is inspired by [lordware's profile](https://github.com/lordware); the artwork, copy, and generator here are specific to Luca.

## Design

The palette is near-black `#080c12`, cool white `#ecf3ff`, icy blue `#75baff`, and steel `#8b9fb8`. Panels have square corners, thin borders, small metadata, subtle scan textures, and monospace text. Each full-width panel has a 480px mobile version selected below 600px viewport width.

All motion is CSS inside SVG images: an orbiting chip monogram, cursor, rotating project focus, boot sequence, hex scan, row highlights, and language bars. `prefers-reduced-motion: reduce` disables every animation. Base geometry keeps the data readable when animations are disabled; the first ticker item stays visible. A plain-text version of all public data is linked at the foot of the README.

The boot and hex panels are decorative profile illustrations. They do not claim a successful CI run, hardware telemetry, or live server health.

## Data and refresh

Run from the repository root using Python 3.12:

```sh
python scripts/collect_public.py
python scripts/render_profile.py
python -m unittest discover -s tests -v
```

The collector writes `assets/profile-data.json`. The renderer creates `assets/*.svg` and `assets/profile.txt`. Edit the renderer to change the art; generated SVG edits will be replaced on refresh.

`.github/workflows/profile.yml` refreshes the public snapshot daily and can be run manually. The GitHub token is used only through the environment. No third-party stats-image host, hosted font, JavaScript, or external animation service is required to display the page.

- Repository stats include the user's currently public owned repositories. Stars exclude forks.
- Language percentages represent source bytes in original public repositories, excluding the profile repository. They are not a proficiency score.
- Repository tables exclude forks and the profile repository.
- The terminal log samples up to three commits per original public repository, keeps the newest eight in the snapshot, and displays six. It includes dates and hash labels only. No commit messages or author identities are copied. The text view also includes the available public event feed filtered to currently public owned repositories. These are samples, not complete contribution history. Dates use UTC.
- Collection errors fail the run before replacing the saved public snapshot.

Before publishing, validate the GitHub-rendered Markdown, desktop/mobile images, SVG XML, generated links, public-only filtering tests, and the first hosted refresh run.
