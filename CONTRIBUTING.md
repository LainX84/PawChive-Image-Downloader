# Contributing

Thanks for your interest in improving PawChive Image Downloader! Bug reports, ideas and pull requests
are welcome at <https://github.com/LainX84/PawChive-Image-Downloader>.

## Development setup

```bash
git clone https://github.com/LainX84/PawChive-Image-Downloader.git
cd PawChive-Image-Downloader
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest
```

Run the application from a terminal with logs on the console:

```bash
python PawChiveDownloader.pyw --console
```

Regenerate the README screenshots and the application icons (no network access needed):

```bash
python tools/make_screenshots.py docs/screenshots
python -m pip install pillow && python tools/make_icons.py
```

Build a standalone package for your platform (the same script runs in the release workflow):

```bash
python -m pip install -r requirements-build.txt
python tools/build.py
```

## Ground rules

- **Never contact the real website in automated tests.** Use the simulated site in
  `tests/conftest.py` (respx) and fixtures in `tests/fixtures/`.
- **Be polite to PawChive.** Do not lower the minimum request delay, raise concurrency limits, add
  proxy/IP rotation or try to bypass CAPTCHAs, anti-bot protections or authentication.
- **Never log secrets.** Cookies and tokens go through `SessionStore` and are redacted by the
  logging filter; do not add code paths that print them.
- **Never overwrite archived files.** All placement goes through `archive.organizer.Organizer`.
- Keep the engine (`core`, `monitor`, `downloads`, `site`, `storage`, `recognition`, `archive`) free
  of Qt imports.
- Use type hints, small functions and clear names.

## Text and translations

- Source code, comments, logs and documentation are written in **English**.
- Every text shown to the user is written in English and wrapped in `_()` from
  `pawchive_downloader.i18n`, for example `_("Pause selected")` or `_("{0} new files", count)`.
  Use `{0}`, `{1}` placeholders (not f-strings) so that the text can be translated.
- Add the Italian translation of new texts to `src/pawchive_downloader/i18n_it.py` (same
  placeholders). Untranslated texts simply appear in English.
- Log messages stay in English and are not translated.

## Colours and themes

Do not hard-code colours. Use the palette in `ui/theme.py` (`color("accent")`, `status_color(...)`)
or object names styled by the stylesheet, so that both the light and the dark theme work.

## Changing the database

Add a new numbered file in `src/pawchive_downloader/storage/migrations/` (for example
`0003_add_something.sql`). Never edit a migration that has been released.

## When PawChive changes

1. Reproduce with the browser developer tools and update `docs/website-analysis.md`.
2. Adjust `site/api.py` (parsing and validation) and add a fixture showing the new format.
3. Add a test, then fix.

## Releasing

1. Update the version in `src/pawchive_downloader/version.py` and `pyproject.toml`.
2. Move the entries under **Unreleased** in `CHANGELOG.md` to a new version section.
3. Commit, then push a tag with the same version: `git tag v1.0.1 && git push origin v1.0.1`.
4. The *Build and release* workflow tests and builds Windows, Linux and macOS (Intel and Apple
   Silicon) packages and publishes them on the GitHub release with the changelog section.

## Pull requests

- One topic per pull request, with tests.
- Update `CHANGELOG.md` under **Unreleased**.
- Make sure `python -m pytest` passes.
