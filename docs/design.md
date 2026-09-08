# Manifest

Luca's GitHub profile is a single SVG document with numbered sections, a ruled project inventory, language composition, recent commits, account totals and contribution streaks.

## Appearance

The light edition uses cool white paper, graphite text, and cobalt annotations. The dark edition uses charcoal paper (`#161b22`), soft white text (`#e6edf3`), and blue annotations (`#8aaaff`). Both retain the same content and layout. A `<picture>` in the README selects the edition for the visitor's theme and a 480px adaptation for narrow viewports.

The barcode scan is the only animation and stops for `prefers-reduced-motion: reduce`. The image has no scripts, external images or fonts. The top-left accent strip is intentionally absent.

Account totals and streaks use the same monospace numbers, margins and rules as the rest of the document. The README contains only the adaptive picture; it has no separate project-link block or activity heading. The SVG description and `assets/profile.txt` provide text equivalents. The picture URLs include a version query to replace the cached image from the previous layout; increment it when publishing another visual revision.

## Data and refresh

Run from the repository root using Python 3.12:

```sh
python scripts/collect_public.py
python scripts/collect_activity.py
python scripts/render_profile.py
python -m unittest discover -s tests -v
```

`collect_public.py` writes `assets/profile-data.json`; `collect_activity.py` writes `assets/activity-data.json`. The renderer reads both snapshots and creates four desktop/mobile, light/dark SVGs and `assets/profile.txt`. Change the renderer to edit the design, since each refresh replaces the generated assets.

`.github/workflows/profile.yml` refreshes both snapshots daily at 07:20 UTC and supports manual runs. Only the GitHub API collector receives the GitHub token.

- Repository counts include currently public repositories owned by this account. Stars exclude forks.
- Languages describe source bytes in original public repositories, excluding the profile repository. The graphic groups the two largest languages and all remaining languages as Other; these are not proficiency scores.
- The inventory features public original projects. It excludes forks and the profile repository.
- The collector samples up to three commits per original public repository, including this profile, and retains the newest eight. The document shows three commit references. No commit messages or author identities are copied from GitHub.
- The text view also includes the available public event feed, filtered to currently public owned repositories. Event and commit samples are not a complete contribution history. Dates use UTC.
- Collection failures leave the saved public snapshot intact.

Account totals still come from the original `github-readme-xi-three.vercel.app` deployment with `include_all_commits=true` and the existing `count_private=true` option. Coverage depends on that deployment's GitHub token and GitHub's index, so these totals can include private activity and differ from the owned public repository counts. Contribution totals, daily streaks and date ranges come from `streak-stats.demolab.com`; contributions include more than commits.

The activity collector saves only validated numbers, rank and date labels. It does not pass a token to either service or embed their SVGs. A failed collection leaves the saved snapshot intact and stops the workflow before it publishes assets. Service caches can still delay changes to the numbers.

## Python structure

`collect_public.py` separates profile, repository, language, commit and event reads into small helpers; `collect()` puts their results together. `collect_activity.py` handles the two activity services. `render_profile.py` has one function per document section and a shared metric renderer for number sizing and labels. Network calls stay out of the renderer.

Validation covers public-only collection, XML escaping, empty snapshots, data calculations, theme consistency, responsive assets, and the hosted refresh workflow.
