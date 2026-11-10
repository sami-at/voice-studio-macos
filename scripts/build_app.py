"""Build a tiny native Finder launcher; keep Python and models in the project."""
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / 'Voice Studio.app'

def make_icon():
    """Draw a macOS-style icon: inset squircle, soft shadow, gradient, mint waveform."""
    from PySide6.QtCore import Qt, QRectF, QPointF
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen

    # Big Sur proportions: an 824 pt rounded square centred on a 1024 pt canvas.
    INSET, SIDE, RADIUS = 100, 824, 185
    BOX = QRectF(INSET, INSET, SIDE, SIDE)
    # Half-heights of the bars, shaped like a spoken phrase rather than an equalizer.
    # Small icons get fewer, fatter bars, which stay legible where thin ones turn to mush.
    SHAPES = {
        16: ([150, 290, 195], 150, 96),
        32: ([120, 232, 300, 188, 108], 86, 58),
        0: ([84, 158, 242, 288, 206, 138, 78], 56, 40),
    }

    def paint(painter, bars, bar_width, gap):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        # Soft contact shadow: stacked translucent squircles, weighted downward.
        for i in range(14, 0, -1):
            spread = i * 1.7
            drop = 10 + spread * 0.55
            painter.setBrush(QColor(12, 38, 40, 4))
            painter.drawRoundedRect(BOX.adjusted(-spread, -spread + drop, spread, spread + drop),
                                    RADIUS + spread, RADIUS + spread)

        body = QPainterPath()
        body.addRoundedRect(BOX, RADIUS, RADIUS)
        painter.setClipPath(body)

        gradient = QLinearGradient(QPointF(INSET, INSET), QPointF(INSET, INSET + SIDE))
        gradient.setColorAt(0.0, QColor('#3fcbb4'))
        gradient.setColorAt(0.45, QColor('#2a9d8f'))
        gradient.setColorAt(1.0, QColor('#14575c'))
        painter.setBrush(gradient)
        painter.drawPath(body)

        # Gloss across the top third keeps it from reading as a flat rectangle.
        gloss = QLinearGradient(QPointF(INSET, INSET), QPointF(INSET, INSET + SIDE * 0.55))
        gloss.setColorAt(0.0, QColor(255, 255, 255, 56))
        gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(gloss)
        painter.drawPath(body)

        x = 512 - (len(bars) * bar_width + (len(bars) - 1) * gap) / 2
        for half in bars:
            bar = QLinearGradient(QPointF(0, 512 - half), QPointF(0, 512 + half))
            bar.setColorAt(0.0, QColor('#ffffff'))
            bar.setColorAt(1.0, QColor('#d8f3ec'))
            painter.setBrush(bar)
            painter.drawRoundedRect(QRectF(x, 512 - half, bar_width, half * 2),
                                    bar_width / 2, bar_width / 2)
            x += bar_width + gap

        painter.setClipping(False)
        # Hairline edge so the icon stays defined on light and dark backgrounds.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 46), 3))
        painter.drawRoundedRect(BOX.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS, RADIUS)

    icons = ROOT / 'assets' / 'VoiceStudio.iconset'
    icons.mkdir(parents=True, exist_ok=True)
    for size in [16, 32, 128, 256, 512]:
        for scale in [1, 2]:
            dim = size * scale
            image = QImage(dim, dim, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.scale(dim / 1024, dim / 1024)
            paint(painter, *SHAPES[dim if dim in SHAPES else 0])
            painter.end()
            suffix = '@2x' if scale == 2 else ''
            image.save(str(icons / f'icon_{size}x{size}{suffix}.png'))
            if dim == 1024:
                image.save(str(ROOT / 'assets' / 'icon.png'))
    subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(icons), '-o', str(ROOT / 'assets' / 'VoiceStudio.icns')], check=True)


def main():
    make_icon()
    macos, resources = BUNDLE / 'Contents' / 'MacOS', BUNDLE / 'Contents' / 'Resources'
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    (resources / 'project-path.txt').write_text(str(ROOT))
    import shutil
    shutil.copy2(ROOT / 'assets' / 'VoiceStudio.icns', resources / 'VoiceStudio.icns')
    info = {'CFBundleName': 'Voice Studio', 'CFBundleDisplayName': 'Voice Studio',
            'CFBundleIdentifier': 'local.voicestudio.desktop', 'CFBundleVersion': '1',
            'CFBundleShortVersionString': '1.0.0', 'CFBundlePackageType': 'APPL',
            'CFBundleExecutable': 'VoiceStudio', 'CFBundleIconFile': 'VoiceStudio',
            'LSMinimumSystemVersion': '26.0', 'NSHighResolutionCapable': True,
            'NSHumanReadableCopyright': 'Local voice narration · Voice Studio'}
    with (BUNDLE / 'Contents' / 'Info.plist').open('wb') as out:
        plistlib.dump(info, out)
    source = ROOT / 'scripts' / 'launcher.c'
    subprocess.run(['/usr/bin/clang', '-O2', '-arch', 'arm64', str(source), '-o', str(macos / 'VoiceStudio')], check=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(BUNDLE)], check=True)
    print(BUNDLE)

if __name__ == '__main__':
    main()
