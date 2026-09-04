import re, glob, struct, os
AVAIL_W, AVAIL_H = 174.0, 235.0   # A4 minus 18mm margins, minus running header
MIN_PT = 8.0
print(f"{'file':<18} {'logical':>12}  {'aspect':>6}  {'@fullwidth':>18} {'label':>7}  verdict")
for f in sorted(glob.glob("/tmp/cppdf/dia/p*.svg")):
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', open(f).read(2000))
    w, h = float(vb.group(1)), float(vb.group(2))
    fpx = float(re.search(r'"fontSize":"(\d+)px"', open(f).read(3000)).group(1)) if re.search(r'"fontSize":"(\d+)px"', open(f).read(3000)) else 17.0
    # scale to fit width, then clamp by height
    s = min(AVAIL_W / w, AVAIL_H / h)
    pt = fpx * s / 25.4 * 72
    max_w_px = AVAIL_W / (MIN_PT * 25.4 / 72 / fpx)
    print(f"{os.path.basename(f):<18} {w:>5.0f}x{h:<6.0f} {w/h:>6.2f}  {w*s:>7.1f}x{h*s:<7.1f}mm {pt:>6.1f}pt  "
          f"{'OK' if pt >= MIN_PT else f'TOO SMALL (need width <= {max_w_px:.0f}px)'}")
