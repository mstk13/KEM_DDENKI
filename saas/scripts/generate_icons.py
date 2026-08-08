"""アプリアイコン（ヘルメット×稲妻）を生成する。

static/img/icon.svg と同じ図形を Pillow で描き、PWA・favicon・
ホーム画面アイコン用の PNG を書き出す。SVG を正とし、本スクリプトは
ラスタ版を作るためのもの。図形を変えるときは両方を揃えること。

実行:
    docker compose exec web python scripts/generate_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "img"

SIZE = 512
CORNER_RADIUS = 112

# 明るいオレンジのグラデーション（左上→右下）
GRAD_FROM = (255, 183, 71)   # #FFB747
GRAD_TO = (255, 107, 44)     # #FF6B2C

HELMET_DOME = (255, 255, 255)
HELMET_BRIM = (222, 229, 238)        # つばは一段暗くしてドームと分離させる
HELMET_BRIM_TOP = (247, 249, 252)
BOLT = (255, 209, 26)        # #FFD11A
BOLT_EDGE = (214, 158, 0)    # 濃いめの縁で背景から浮かせる

# 512px キャンバス上の座標。
# ドームは「幅より高さを稼ぐ」形にしないと器や帽子に見えてしまう。
DOME_BOX = (128, 150, 384, 480)      # 上半分だけ描いてドームにする
BRIM_BOX = (96, 288, 416, 346)       # つばはドームより少しだけ広い程度に留める
BRIM_TOP_BOX = (108, 284, 404, 332)  # つば上面のハイライト
BOLT_POINTS = [
    (276, 180),
    (222, 248),
    (251, 248),
    (239, 300),
    (293, 232),
    (264, 232),
]


def _gradient(size: int) -> Image.Image:
    """左上から右下への線形グラデーションを作る。"""
    img = Image.new("RGB", (size, size))
    px = img.load()
    max_t = (size - 1) * 2
    for y in range(size):
        for x in range(size):
            t = (x + y) / max_t
            px[x, y] = (
                round(GRAD_FROM[0] + (GRAD_TO[0] - GRAD_FROM[0]) * t),
                round(GRAD_FROM[1] + (GRAD_TO[1] - GRAD_FROM[1]) * t),
                round(GRAD_FROM[2] + (GRAD_TO[2] - GRAD_FROM[2]) * t),
            )
    return img


def build_icon(rounded: bool = True) -> Image.Image:
    base = _gradient(SIZE).convert("RGBA")

    if rounded:
        mask = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, SIZE - 1, SIZE - 1), radius=CORNER_RADIUS, fill=255
        )
        base.putalpha(mask)

    # ヘルメットと稲妻は別レイヤーに描いてから合成する（アンチエイリアスのため
    # 4倍で描いて縮小する）。
    scale = 4
    layer = Image.new("RGBA", (SIZE * scale, SIZE * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def s(box):
        return tuple(v * scale for v in box)

    # つば（先に描いてドームを重ねる）
    d.ellipse(s(BRIM_BOX), fill=HELMET_BRIM)
    d.ellipse(s(BRIM_TOP_BOX), fill=HELMET_BRIM_TOP)
    # ドーム（上半分）
    d.pieslice(s(DOME_BOX), start=180, end=360, fill=HELMET_DOME)
    # 稲妻
    d.polygon(
        [(x * scale, y * scale) for x, y in BOLT_POINTS],
        fill=BOLT,
        outline=BOLT_EDGE,
        width=2 * scale,
    )

    layer = layer.resize((SIZE, SIZE), Image.LANCZOS)
    return Image.alpha_composite(base, layer)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rounded = build_icon(rounded=True)
    square = build_icon(rounded=False)   # iOS は自前で角丸にするため四角のまま渡す

    targets = [
        ("icon-512.png", rounded, 512),
        ("icon-192.png", rounded, 192),
        ("apple-touch-icon.png", square, 180),
        ("favicon-32.png", rounded, 32),
    ]
    for name, src, size in targets:
        img = src.resize((size, size), Image.LANCZOS)
        img.save(OUT_DIR / name)
        print(f"生成: {name} ({size}x{size})")

    # favicon.ico は複数サイズを1ファイルに入れる
    rounded.resize((64, 64), Image.LANCZOS).save(
        OUT_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)]
    )
    print("生成: favicon.ico (16/32/48)")


if __name__ == "__main__":
    main()
