# Third-party notices

PawChive Image Downloader is released under the [MIT License](LICENSE). It uses the open-source
components below, which belong to their respective authors and are distributed under their own
licenses. The release builds published on GitHub include these components unmodified.

| Component | License | Project |
|---|---|---|
| Python | PSF License Agreement | <https://www.python.org/> |
| Qt 6 and PySide6 (Qt for Python) | GNU LGPL v3 | <https://www.qt.io/qt-for-python> |
| httpx, httpcore | BSD 3-Clause | <https://www.python-httpx.org/> |
| h11 | MIT | <https://github.com/python-hyper/h11> |
| anyio, sniffio | MIT / Apache 2.0 | <https://github.com/agronholm/anyio> |
| idna | BSD 3-Clause | <https://github.com/kjd/idna> |
| certifi | MPL 2.0 | <https://github.com/certifi/python-certifi> |
| keyring and its jaraco.* helpers | MIT | <https://github.com/jaraco/keyring> |
| platformdirs | MIT | <https://github.com/tox-dev/platformdirs> |
| PyInstaller bootloader (release builds only) | GPL 2.0 with bootloader exception | <https://pyinstaller.org/> |

Development and test tools (not shipped): pytest (MIT), respx (BSD 3-Clause), Pillow (MIT-CMU, used
to generate the icons).

## Qt / PySide6 (LGPL v3)

Qt and PySide6 are used under the GNU Lesser General Public License v3. The release builds ship the
unmodified Qt and PySide6 libraries as separate shared libraries, so you can replace them with your
own build. The source code of Qt is available at <https://code.qt.io/> and the source code of PySide6
at <https://code.qt.io/cgit/pyside/pyside-setup.git/>. The full license text is available at
<https://www.gnu.org/licenses/lgpl-3.0.html>.

## Content

The files the application downloads come from PawChive (pawchive.pw), which mirrors publications of
the original platforms. They are **not** part of this project and are **not** covered by its
license: every file remains the property of its creator. See [DISCLAIMER.md](DISCLAIMER.md).

## Icons

The application icon and the interface icons are original drawings made for this project and are
released under the same MIT License.
