"""License, disclaimer and third-party notices shown in the About page.

The same texts are published in LICENSE, DISCLAIMER.md and
THIRD_PARTY_NOTICES.md at the root of the repository.
"""

from __future__ import annotations

from .version import COPYRIGHT

MIT_LICENSE = f"""MIT License

{COPYRIGHT}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# Each paragraph is translated separately in the interface (see i18n_it.py).
DISCLAIMER = (
    "PawChive Image Downloader is an unofficial, independent project. It is not affiliated with, endorsed by "
    "or sponsored by PawChive, Patreon or any of the creators whose publications it can download.",
    "The software only automates access to content that PawChive already makes publicly available. It does "
    "not bypass logins, paywalls, CAPTCHAs, rate limits or other protections, and it never will.",
    "All artworks, images and other files belong to their respective creators and copyright holders. Using "
    "this software does not give you any right over them. Keep downloads for your own personal archive, do "
    "not redistribute, sell or re-upload them without the creator's permission, and please support the "
    "artists you follow through their official channels.",
    "You alone are responsible for how you use the software and for complying with the laws of your country "
    "and with the terms of service of PawChive and of the original platforms. If you are asked to stop, or "
    "a creator does not want their work archived, respect that.",
    "The software is provided \"as is\", without warranty of any kind. The author is not liable for any "
    "damage, data loss, account restriction or legal consequence arising from its use (see the MIT License).",
    "PawChive, Patreon and all other names and trademarks mentioned belong to their respective owners and are "
    "used only to describe what the software works with.",
)

# (component, license, project URL)
THIRD_PARTY = (
    ("Python", "PSF License Agreement", "https://www.python.org/"),
    ("Qt 6 / PySide6 (Qt for Python)", "GNU LGPL v3", "https://www.qt.io/qt-for-python"),
    ("httpx, httpcore", "BSD 3-Clause", "https://www.python-httpx.org/"),
    ("h11", "MIT", "https://github.com/python-hyper/h11"),
    ("anyio, sniffio", "MIT / Apache 2.0", "https://github.com/agronholm/anyio"),
    ("idna", "BSD 3-Clause", "https://github.com/kjd/idna"),
    ("certifi", "MPL 2.0", "https://github.com/certifi/python-certifi"),
    ("keyring and jaraco.* helpers", "MIT", "https://github.com/jaraco/keyring"),
    ("platformdirs", "MIT", "https://github.com/tox-dev/platformdirs"),
    ("PyInstaller bootloader (release builds only)", "GPL 2.0 with bootloader exception",
     "https://pyinstaller.org/"),
)
