"""Dev-only: slide screenshots -> one contact sheet. Usage: python tools/contact.py runs/x [n]"""
import subprocess, sys
from pathlib import Path
from PIL import Image
d = Path(sys.argv[1]); n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
subprocess.run([sys.executable, str(Path(__file__).parent / "slide_shots.py"), str(d / "index.html"), str(n)])
ims = [Image.open(d / f"slide{i:02d}.png").resize((640, 400)) for i in range(n) if (d / f"slide{i:02d}.png").exists()]
W = Image.new("RGB", (640 * 3, 400 * ((len(ims) + 2) // 3)), "white")
for i, im in enumerate(ims): W.paste(im, ((i % 3) * 640, (i // 3) * 400))
W.save(d / "contact.png")
