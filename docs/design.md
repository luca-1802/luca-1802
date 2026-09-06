# Profile design

The profile README is the landing page. Edit `README.md` for text, public project links, and statistics.

## Terminal artwork

- `assets/terminal.svg` is the desktop header (960 × 416).
- `assets/terminal-mobile.svg` is the compact header (480 × 420), selected by the README's `<picture>` at viewport widths up to 600px.
- Both are hand-authored vector assets. They need no build step, JavaScript, hosted font, or animation service.
- Palette: background `#10141b`, border `#283140`, primary text `#edf3f8`, secondary text `#a6b2c2`, accent `#8ff0c8`.
- The command types in, the content enters, and the cursor blinks briefly. All motion finishes within four seconds; reduced-motion preferences disable it. Base SVG attributes show the complete content if animation is unavailable.
- Keep the SVG title, description, and the README image alt text synchronized when changing the introduction.

## GitHub constraints

The README uses GitHub-compatible Markdown, `<picture>`, and `<details>`. Animation lives inside the SVG images. The profile itself needs no custom page CSS or scripts.

The optional statistics retain the pre-existing providers and load live data from those services. Their availability and cache refresh are controlled by the providers. The introduction and project links do not depend on them.

Before publishing, preview the rendered Markdown at desktop and mobile sizes, verify the mobile image is selected, inspect both SVGs, and check the statistics disclosure and repository links. Only link public repositories from the profile.
