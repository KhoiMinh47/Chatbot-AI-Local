from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
FRAMES_DIR = ROOT / "docs" / "assets" / "web-demo-frames"
OUT = ROOT / "docs" / "assets" / "rag-chat-demo.gif"


def main() -> None:
    frame_paths = sorted(FRAMES_DIR.glob("frame-*.png"))
    if not frame_paths:
        raise SystemExit("Không có frame để tạo GIF")

    frames = []
    for frame_path in frame_paths:
        image = Image.open(frame_path).convert("RGB")
        image.thumbnail((960, 540))
        frames.append(image.convert("P", palette=Image.Palette.ADAPTIVE, colors=128))

    # GIF không lưu FPS như video; duration 42ms tương đương xấp xỉ 24fps.
    # Lặp frame để demo đạt khoảng 30 giây.
    repeated = []
    repeat_each = max(1, round(720 / len(frames)))
    for frame in frames:
        repeated.extend([frame] * repeat_each)
    repeated = repeated[:720]

    repeated[0].save(
        OUT,
        save_all=True,
        append_images=repeated[1:],
        duration=42,
        loop=0,
        optimize=True,
    )
    print(OUT)


if __name__ == "__main__":
    main()
