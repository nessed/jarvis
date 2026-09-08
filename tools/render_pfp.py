r"""Render Jarvis's avatar: the ambient circle at rest.

Blueprint section 5. The circle is Jarvis's whole visual language, and the
WhatsApp avatar is its **Sleeping** state -- "tiny / static / dim" -- because
that is what it is doing every time the avatar is on screen. So this is not a
picture *of* Jarvis; it is Jarvis, idle.

This script exists so the phone and the second monitor cannot drift apart into
two different-looking things. The colours live in the blueprint as tokens,
they live here as constants, and both are the same three numbers: change them
in one place, re-run, and the avatar follows.

    .venv\Scripts\python.exe tools/render_pfp.py
    .venv\Scripts\python.exe tools/render_pfp.py --out somewhere/else.png

Why a ring and not a filled disc: WhatsApp already crops every avatar to a
circle, so a disc inside that is a circle inside a circle and reads as a moon.
An annulus reads as a drawn object, and its dark centre still has structure at
the 40 pixels a chat list actually gives it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

#: Blueprint section 5, "The circle's palette". Keep these in step with it.
IDLE_CORE = (0xFF, 0xD2, 0x96)
IDLE_GLOW = (0xF0, 0x84, 0x22)
GROUND = (0x0A, 0x09, 0x08)

#: 1024 because WhatsApp wants at least 640 and downscales; rendering large and
#: letting it shrink beats rendering small and letting it blur.
SIZE = 1024

# All as fractions of SIZE, so the geometry survives a resolution change.
RING_RADIUS = 0.272
RING_THICKNESS = 0.036
HALO_RADIUS = 0.20
RING_GAIN = 0.95
INNER_FILL = 0.075
#: A touch stronger above centre, so the light has a direction and the result
#: does not look machine-symmetrical.
TOP_LIT_BIAS = 0.16


def _fields(size: int) -> tuple[np.ndarray, np.ndarray]:
    axis = np.arange(size, dtype=np.float64) + 0.5 - size / 2
    x, y = np.meshgrid(axis, axis)
    return np.hypot(x, y), y


def render(size: int = SIZE) -> Image.Image:
    """The idle circle, as an emissive ring on near-black."""
    radius = size * RING_RADIUS
    thickness = size * RING_THICKNESS
    halo_radius = size * HALO_RADIUS
    r, y = _fields(size)

    # A gaussian band centred on the ring radius: soft both sides, no seam.
    band = np.exp(-0.5 * ((r - radius) / (thickness * 0.5)) ** 2)

    halo = np.exp(-0.5 * ((r - radius) / (halo_radius * 0.5)) ** 2)
    halo = halo * (1.0 + TOP_LIT_BIAS * np.clip(-y / (size / 2), -1, 1)) * 0.20

    # A faint wash inside the ring so the centre is not dead black.
    inside = (1.0 - np.clip(r / max(radius - thickness * 0.6, 1.0), 0.0, 1.0)) ** 2.2 * INNER_FILL

    ground = np.array(GROUND, dtype=np.float64) / 255.0
    core = np.array(IDLE_CORE, dtype=np.float64) / 255.0
    glow = np.array(IDLE_GLOW, dtype=np.float64) / 255.0

    out = np.repeat(ground[None, None, :], size, axis=0).repeat(size, axis=1)
    out = out + np.clip(halo + inside, 0.0, 1.0)[..., None] * glow[None, None, :]
    lit = np.clip(band * RING_GAIN, 0.0, 1.0)
    out = out * (1.0 - lit[..., None]) + lit[..., None] * core[None, None, :]

    image = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), mode="RGB")
    # Unifies the layers so no ring shows a banding seam after JPEG-ing.
    return image.filter(ImageFilter.GaussianBlur(radius=1.0))


def circle_preview(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """The avatar as WhatsApp shows it: circle-cropped, at three real sizes.

    Judging this at 1024 square is how you end up with something that looks
    good in an image viewer and like a smudge in a chat list.
    """
    sheet = Image.new("RGB", (560, 200), background)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, image.size[0] - 1, image.size[1] - 1), fill=255)
    for index, px in enumerate((128, 72, 48)):
        sheet.paste(
            image.resize((px, px), Image.LANCZOS),
            (40 + index * 170, (200 - px) // 2),
            mask.resize((px, px), Image.LANCZOS),
        )
    return sheet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render Jarvis's idle-circle avatar")
    parser.add_argument("--out", type=Path, default=Path("JARVIS-pfp.png"))
    parser.add_argument("--size", type=int, default=SIZE)
    parser.add_argument(
        "--previews",
        action="store_true",
        help="also write circle-cropped previews on WhatsApp's light and dark backgrounds",
    )
    args = parser.parse_args(argv)

    image = render(args.size)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out, optimize=True)
    print(f"wrote {args.out} ({args.size}x{args.size})")

    if args.previews:
        for name, background in (("light", (237, 237, 237)), ("dark", (17, 27, 33))):
            path = args.out.with_name(f"{args.out.stem}-on-{name}.png")
            circle_preview(image, background).save(path)
            print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
