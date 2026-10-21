"""Shared GUI identity. Import only when starting a graphical entry point."""
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def application_icon():
    # PNG also works with Essentials wheels that do not ship the SVG plugin.
    return QIcon(str(Path(__file__).with_name('assets')/'mcpy.png'))


def _macos_application_name():
    """Name an unbundled Python GUI before Cocoa registers it with the Dock."""
    import ctypes
    objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    ctypes.CDLL('/System/Library/Frameworks/Foundation.framework/Foundation')
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value

    def send(receiver, selector, *args):
        call = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                               *([ctypes.c_void_p] * len(args)))(address)
        return call(receiver, objc.sel_registerName(selector), *args)

    def string(value):
        return send(objc.objc_getClass(b'NSString'), b'stringWithUTF8String:',
                    ctypes.cast(ctypes.c_char_p(value), ctypes.c_void_p))

    pool = send(objc.objc_getClass(b'NSAutoreleasePool'), b'new')
    try:
        name = string(b'mcpy')
        bundle = send(objc.objc_getClass(b'NSBundle'), b'mainBundle')
        info = send(bundle, b'infoDictionary')
        for key in (b'CFBundleName', b'CFBundleDisplayName'):
            send(info, b'setObject:forKey:', name, string(key))
        send(info, b'setObject:forKey:', string(b'net.easecation.mcpy'), string(b'CFBundleIdentifier'))
        process = send(objc.objc_getClass(b'NSProcessInfo'), b'processInfo')
        send(process, b'setProcessName:', name)
    finally:
        send(pool, b'drain')


def create_application(arguments=None):
    app = QApplication.instance()
    if app is None:
        if sys.platform == 'darwin':
            _macos_application_name()
        QApplication.setApplicationName('mcpy')
        app = QApplication(arguments or [])
    app.setApplicationName('mcpy')
    app.setApplicationDisplayName('mcpy')
    app.setWindowIcon(application_icon())
    return app
