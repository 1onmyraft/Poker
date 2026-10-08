'''
Generate the cartoon bot avatars in resources/avatars/ (needs Pillow; run once).

    python tools/make_avatars.py

Each style gets <kind>.png and a dimmed <kind>_dim.png (shown after a fold).
Drawn at 4x and downsampled for smooth edges. Saved as 8-bit RGBA, non-interlaced,
so the GUI's built-in PNG decoder can read them on old Tk too.
'''
import math
import os

from PIL import Image, ImageDraw, ImageEnhance

S = 4                      # supersampling
SIZE = 72
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'avatars')
SKIN = (241, 194, 150)
INK = (35, 30, 30)


def canvas(bg):
    img = Image.new('RGBA', (SIZE * S, SIZE * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse(sc(1, 1, 71, 71), fill=bg, outline=(255, 255, 255), width=3 * S)
    return img, d


def sc(*v):
    return tuple(x * S for x in v)


def face(d, cx=36, cy=40, r=19, skin=SKIN):
    d.ellipse(sc(cx - r, cy - r, cx + r, cy + r), fill=skin, outline=INK, width=S)


def eyes(d, y=38, dx=7, r=2.6, pupil=INK, white=False, rw=4.5):
    for x in (36 - dx, 36 + dx):
        if white:
            d.ellipse(sc(x - rw, y - rw, x + rw, y + rw), fill=(255, 255, 255), outline=INK, width=S)
        d.ellipse(sc(x - r, y - r, x + r, y + r), fill=pupil)


def smile(d, y=46, w=8, h=5, width=2):
    d.arc(sc(36 - w, y - h, 36 + w, y + h), 20, 160, fill=INK, width=width * S)


def finish(img, kind):
    small = img.resize((SIZE, SIZE), Image.LANCZOS)
    small.save(os.path.join(OUT, kind + '.png'), optimize=False)
    dim = ImageEnhance.Brightness(ImageEnhance.Color(small).enhance(0.15)).enhance(0.55)
    dim.putalpha(small.getchannel('A'))
    dim.save(os.path.join(OUT, kind + '_dim.png'), optimize=False)


def you():
    img, d = canvas((30, 90, 160))
    d.ellipse(sc(25, 14, 47, 36), fill=(255, 255, 255))
    d.pieslice(sc(13, 38, 59, 84), 180, 360, fill=(255, 255, 255))
    finish(img, 'You')


def hunter():
    img, d = canvas((46, 94, 52))
    face(d)
    d.polygon(sc(15, 30, 57, 30, 50, 15, 22, 15), fill=(239, 108, 0), outline=INK)   # cap
    d.rectangle(sc(12, 28, 60, 32), fill=(214, 90, 0))                                 # brim
    for x in (29, 43):                                                                 # narrowed eyes
        d.line(sc(x - 4, 39, x + 4, 39), fill=INK, width=2 * S)
    d.line(sc(31, 48, 41, 47), fill=INK, width=2 * S)
    cx, cy, r = 57, 55, 9                                                               # crosshair badge
    d.ellipse(sc(cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255), outline=(198, 40, 40), width=2 * S)
    d.line(sc(cx - r, cy, cx + r, cy), fill=(198, 40, 40), width=S)
    d.line(sc(cx, cy - r, cx, cy + r), fill=(198, 40, 40), width=S)
    finish(img, 'Hunter')


def antemax():
    img, d = canvas((106, 27, 154))
    face(d)
    for i in range(7):                                                                 # spiky hair
        x = 18 + i * 6
        d.polygon(sc(x, 27, x + 6, 27, x + 3, 13 + (i % 2) * 4), fill=(255, 202, 40))
    d.rounded_rectangle(sc(20, 33, 34, 42), radius=3 * S, fill=INK)                    # shades
    d.rounded_rectangle(sc(38, 33, 52, 42), radius=3 * S, fill=INK)
    d.line(sc(34, 36, 38, 36), fill=INK, width=2 * S)
    smile(d, y=47, w=9)
    d.polygon(sc(57, 44, 51, 57, 56, 57, 52, 68, 63, 52, 57, 52, 61, 44), fill=(255, 235, 59), outline=INK)
    finish(img, 'AnteMax')


def maniac():
    img, d = canvas((198, 40, 40))
    for i in range(9):                                                                 # wild hair
        a = math.radians(200 + i * 17)
        d.line(sc(36 + 14 * math.cos(a), 36 + 14 * math.sin(a), 36 + 27 * math.cos(a), 34 + 27 * math.sin(a)),
               fill=(255, 112, 67), width=4 * S)
    face(d, r=18)
    d.ellipse(sc(23, 31, 34, 42), fill=(255, 255, 255), outline=INK, width=S)          # mismatched eyes
    d.ellipse(sc(39, 33, 48, 42), fill=(255, 255, 255), outline=INK, width=S)
    d.ellipse(sc(27, 33, 31, 37), fill=INK)
    d.ellipse(sc(43, 38, 46, 41), fill=INK)
    d.chord(sc(25, 40, 47, 56), 0, 180, fill=(255, 255, 255), outline=INK, width=S)   # big grin
    for x in (30, 36, 42):
        d.line(sc(x, 48, x, 55), fill=INK, width=S)
    finish(img, 'Maniac')


def antetag():
    img, d = canvas((55, 71, 79))
    d.line(sc(36, 14, 36, 22), fill=(200, 200, 200), width=2 * S)                      # antenna
    d.ellipse(sc(32, 9, 40, 17), fill=(0, 229, 255))
    d.rounded_rectangle(sc(17, 22, 55, 58), radius=7 * S, fill=(176, 190, 197), outline=INK, width=S)
    d.rounded_rectangle(sc(22, 31, 50, 42), radius=4 * S, fill=(38, 50, 56))
    d.ellipse(sc(25, 33, 32, 40), fill=(0, 229, 255))
    d.ellipse(sc(40, 33, 47, 40), fill=(0, 229, 255))
    for x in range(26, 48, 5):
        d.rectangle(sc(x, 48, x + 3, 52), fill=(38, 50, 56))
    finish(img, 'AnteTAG')


def station():
    img, d = canvas((79, 195, 247))
    d.polygon(sc(46, 38, 62, 26, 62, 50), fill=(255, 145, 0), outline=INK)            # tail
    d.ellipse(sc(10, 24, 52, 52), fill=(255, 167, 38), outline=INK, width=S)          # body
    d.arc(sc(26, 26, 40, 50), 300, 60, fill=(230, 81, 0), width=2 * S)                # gill
    d.ellipse(sc(16, 31, 25, 40), fill=(255, 255, 255), outline=INK, width=S)
    d.ellipse(sc(18, 33, 22, 37), fill=INK)
    d.arc(sc(11, 40, 20, 47), 300, 90, fill=INK, width=S)                              # mouth
    for x, y, r in ((24, 15, 3), (31, 10, 2), (17, 9, 2)):                             # bubbles
        d.ellipse(sc(x - r, y - r, x + r, y + r), outline=(255, 255, 255), width=S)
    finish(img, 'Station')


def nervous():
    img, d = canvas((251, 192, 45))
    face(d)
    d.line(sc(24, 31, 32, 33), fill=INK, width=2 * S)                                  # worried brows
    d.line(sc(48, 31, 40, 33), fill=INK, width=2 * S)
    eyes(d, y=39, r=2.4)
    d.line(sc(28, 49, 32, 47, 36, 49, 40, 47, 44, 49), fill=INK, width=2 * S, joint='curve')
    d.polygon(sc(54, 26, 50, 35, 58, 35), fill=(100, 181, 246))                        # sweat drop
    d.ellipse(sc(50, 31, 58, 39), fill=(100, 181, 246))
    finish(img, 'Nervous')


def scared():
    img, d = canvas((255, 138, 101))
    face(d, skin=(250, 225, 200))
    d.arc(sc(22, 26, 32, 32), 200, 340, fill=INK, width=2 * S)                         # raised brows
    d.arc(sc(40, 26, 50, 32), 200, 340, fill=INK, width=2 * S)
    eyes(d, y=38, white=True, rw=5, r=1.8)
    d.ellipse(sc(32, 46, 40, 55), fill=INK)                                            # "o" mouth
    finish(img, 'Scared')


def terrified():
    img, d = canvas((38, 50, 56))
    d.pieslice(sc(18, 13, 54, 49), 180, 360, fill=(250, 250, 250))                     # ghost
    pts = [(18, 31), (54, 31), (54, 60)]
    for i in range(6):
        pts.append((54 - (i + 0.5) * 6, 54 if i % 2 == 0 else 60))
    pts.append((18, 60))
    d.polygon([v * S for p in pts for v in p], fill=(250, 250, 250))
    d.ellipse(sc(25, 26, 32, 37), fill=INK)
    d.ellipse(sc(40, 26, 47, 37), fill=INK)
    d.ellipse(sc(32, 40, 40, 50), fill=INK)
    finish(img, 'Terrified')


def nit():
    img, d = canvas((120, 144, 156))
    d.polygon(sc(14, 50, 20, 28, 34, 20, 50, 24, 59, 40, 56, 54, 36, 58), fill=(158, 158, 158), outline=INK)
    d.line(sc(26, 38, 32, 38), fill=INK, width=2 * S)                                  # sleepy eyes
    d.line(sc(40, 38, 46, 38), fill=INK, width=2 * S)
    d.line(sc(31, 48, 41, 48), fill=INK, width=2 * S)
    d.line(sc(22, 30, 27, 33), fill=(97, 97, 97), width=S)                             # cracks
    finish(img, 'Nit')


def lag():
    img, d = canvas((255, 112, 67))
    face(d)
    d.chord(sc(16, 14, 56, 44), 180, 360, fill=(33, 150, 243), outline=INK)           # backwards cap
    d.rectangle(sc(12, 27, 22, 31), fill=(25, 118, 210))
    eyes(d, y=39)
    d.arc(sc(30, 42, 46, 52), 10, 120, fill=INK, width=2 * S)                          # smirk
    finish(img, 'LAG')


def tag():
    img, d = canvas((0, 137, 123))
    face(d)
    d.arc(sc(14, 16, 58, 52), 180, 360, fill=(33, 33, 33), width=3 * S)                # headphones
    d.rounded_rectangle(sc(11, 34, 19, 48), radius=2 * S, fill=(33, 33, 33))
    d.rounded_rectangle(sc(53, 34, 61, 48), radius=2 * S, fill=(33, 33, 33))
    eyes(d, y=39)
    d.line(sc(30, 48, 42, 48), fill=INK, width=2 * S)
    finish(img, 'TAG')


def exploit():
    img, d = canvas((40, 53, 147))
    face(d)
    eyes(d, y=39)
    d.ellipse(sc(37, 31, 51, 45), outline=(255, 214, 0), width=2 * S)                 # monocle
    d.line(sc(50, 44, 58, 58), fill=(255, 214, 0), width=2 * S)
    smile(d, y=47, w=6)
    finish(img, 'Exploit')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for fn in (you, hunter, antemax, maniac, antetag, station, nervous, scared, terrified, nit, lag, tag, exploit):
        fn()
    print('wrote avatars to', OUT)
