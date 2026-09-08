# Manifest

Luca's GitHub profile is an original software manifest: a continuous engineering document with a barcode identity, numbered margins, a ruled package inventory, language composition, and a short public changelog.

## Appearance

The light edition uses cool white paper, graphite text, and cobalt annotations. The dark edition uses charcoal paper (`#161b22`), soft white text (`#e6edf3`), and blue annotations (`#8aaaff`). Both retain the same content and layout. A `<picture>` in the README selects the edition for the visitor's theme and a 480px adaptation for narrow viewports.

The barcode scan is decorative. Its CSS animation is contained in the SVG and stops for `prefers-reduced-motion: reduce`. The document stays readable without motion. The generated Manifest has no external fonts, scripts, tracking images, or third-party statistics hosts. Native links below the image lead to the projects and an accessible plain-text version of the Manifest.

The README's separate GitHub activity section restores the original GitHub Readme Stats deployment (`github-readme-xi-three.vercel.app`) and contribution streak card (`streak-stats.demolab.com`). Both use the Manifest's light/dark palettes, select the visitor's theme with `<picture>`, and scale from 450px SVGs to the available width. Descriptive alt text identifies each card and its metrics.

## Data and refresh

Run from the repository root using Python 3.12:

```sh
python scripts/collect_public.py
python scripts/render_profile.py
python -m unittest discover -s tests -v
```

The collector writes `assets/profile-data.json`. The renderer creates the light and dark desktop/mobile Manifest SVGs and `assets/profile.txt`. Edit the renderer or its templates to change the design; generated assets are replaced by each refresh.

`.github/workflows/profile.yml` refreshes the snapshot daily at 07:20 UTC and supports manual runs. The GitHub token is supplied only through the environment.

- Repository counts include currently public repositories owned by this account. Stars exclude forks.
- Languages describe source bytes in original public repositories, excluding the profile repository. The graphic groups the two largest languages and all remaining languages as Other; these are not proficiency scores.
- The inventory features public original projects. It excludes forks and the profile repository.
- The collector samples up to three commits per original public repository, including this profile, and retains the newest eight. The document shows three commit references. No commit messages or author identities are copied from GitHub.
- The text view also includes the available public event feed, filtered to currently public owned repositories. Event and commit samples are not a complete contribution history. Dates use UTC.
- Collection failures leave the saved public snapshot intact.

The activity cards refresh through their original services and GitHub's image cache, independently of the daily Manifest snapshot. The stats card requests all-time commits with `include_all_commits=true` and preserves the old `count_private=true` option. Its coverage depends on the original deployment's GitHub token and GitHub's indexed data, so it can include activity beyond the owned public repositories counted in the Manifest. No token is included in the README. Total contributions and daily streaks come from the separate streak service; contributions are not the same metric as commits. These live cards are not copied into the generated `profile.txt` snapshot.

Validation covers public-only collection, XML escaping, empty snapshots, data calculations, theme consistency, responsive assets, and the hosted refresh workflow.
