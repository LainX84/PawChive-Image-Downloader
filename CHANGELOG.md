# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-19

First public release.

### Monitoring and recognition
- Monitors PawChive authors added by profile or post URL, on a schedule (default every 6 hours) with
  per-author intervals, pause/resume, manual and full rescans, and a periodic full pass that catches
  edits of older posts.
- Downloads only the original files, verified against the SHA-256 embedded in PawChive's file paths;
  previews are never saved as final files. Attached archives, videos and PDFs are kept with the work.
- Recognizes series, volume, part, chapter, issue and page numbers in titles and files each page in
  the right work, in page order, even when pages are published out of order. Sketches and WIPs get a
  separate "… - Sketches" work.
- Never merges similar titles on its own: uncertain publications wait in **Review** and the decision
  is remembered. **Rebuild archive…** re-files an author's archive without downloading anything again.
- Records empty galleries and galleries with previews only, and rechecks them later.

### Downloads
- Reliable engine: `.part` files with HTTP Range resume, integrity checks, atomic moves, a persistent
  queue, exponential back-off and recovery after crashes and restarts.
- **Pause / resume all downloads** from the sidebar, the tray menu or with Ctrl+P. Pausing stops the
  transfers in progress at once and keeps their partial `.part` files, which continue where they
  stopped.
- **Timed pause**: pause for 15 minutes to 8 hours, or until a date and time; downloads resume by
  themselves.
- **Pause single files** ("Pause selected" / "Resume selected"), while the rest of the queue continues.
- **Manual queue order**: "Move to top" and "Move to bottom".
- **Speed limit** for all downloads together (Settings → Requests and retries), applied immediately.
- **Speed and time left** for every download and in total, in the Queue, on the Dashboard and in the
  status bar.
- Polite to the website: throttled requests, limited concurrency, `Retry-After` honoured, automatic
  pause when access is blocked. No proxy rotation and no bypassing of protections.

### Interface
- **English and Italian**, chosen in Settings (default: the system language).
- **Light and dark themes**, or follow the system theme (also when it changes while the app runs).
- Sidebar grouped in collapsible sections, with crisp icons that stay aligned on every platform.
- **Notification-area (tray) icon**: closing the window keeps the app running in the background; the
  icon's menu pauses/resumes downloads (also for a while), scans all authors or quits.
- **Desktop notifications** when a work receives new pages; clicking one opens the work.
- About page with the project links, the license, the disclaimer and the third-party credits.

### Distribution
- Standalone builds for **Windows x64**, **Linux x64**, **macOS Apple Silicon** and **macOS Intel**,
  produced by GitHub Actions for every release (`tools/build.py` builds the same packages locally).
- Released under the MIT License, with a disclaimer (`DISCLAIMER.md`) and third-party notices
  (`THIRD_PARTY_NOTICES.md`).

[Unreleased]: https://github.com/LainX84/PawChive-Image-Downloader/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/LainX84/PawChive-Image-Downloader/releases/tag/v1.0.0
