"""Render the original VaultMove icon to a multi-resolution .ico (+ a 256 px PNG).

    python packaging/make_icon.py      -> packaging/vaultmove.ico, packaging/vaultmove.png
"""

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def png_bytes(img) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def main():
    app = QGuiApplication(sys.argv[:1])  # noqa: F841
    from vaultmove.app.icon import render
    images = [png_bytes(render(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, blobs = b"", b""
    for s, data in zip(SIZES, images):
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    with open(os.path.join(HERE, "vaultmove.ico"), "wb") as f:
        f.write(header + entries + blobs)
    render(256).save(os.path.join(HERE, "vaultmove.png"))
    print("wrote packaging/vaultmove.ico and vaultmove.png")


if __name__ == "__main__":
    main()
