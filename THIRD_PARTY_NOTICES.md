# GUI dependency notices

mcpywrap's own source code is distributed under the MIT License in `LICENSE`.
This notice covers the Qt GUI dependencies, not the complete dependency tree.
Other installed packages retain their own copyright and license notices.

## PySide6, Shiboken6 and Qt

The Windows and macOS GUI uses the official Qt for Python bindings, installed
as `PySide6-Essentials` and its `shiboken6` dependency. The application uses
QtCore, QtGui and QtWidgets; it does not require PyQt or PySide6-Addons.

We select the LGPLv3 licensing option for these dependencies. The inspected
6.11.2 distributions declare `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`.
The Qt libraries used by the application are available under LGPLv3.
Copyright and additional third-party notices remain with the upstream packages.

The mcpywrap wheel does not bundle Qt, PySide6 or Shiboken6 binaries. Package
managers install them separately in the user's Python environment. Users may
replace compatible versions; mcpywrap does not prevent modification or debugging
of these libraries. Retain upstream notices and provide the applicable
corresponding-source access when redistributing these dependencies. A future
frozen application or a change in Qt modules requires a fresh distribution audit.

Upstream licensing and source:

- https://doc.qt.io/qtforpython-6/licenses.html
- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/qtbase.git/

## Native game launcher

The separately downloaded native launcher has its own GPL licensing and
corresponding-source distribution. Changing the Python GUI binding does not
change that launcher's license or permit redistribution of Minecraft binaries.
