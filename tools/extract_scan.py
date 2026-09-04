# -*- coding: utf-8 -*-
"""
스캔 이미지 문제지(텍스트 레이어 없음, 국시원 A3 2단 규격) → 문항별 WebP 크롭. (2024상)

OCR(rapidocr)은 이 스캔에서 한글·문항번호 검출이 불안정해 쓰지 않는다. 대신 레이아웃 규칙을 이용한다:
  - 문항번호 "N."은 본문보다 약 11pt 왼쪽으로 내어쓰기(outdent) 되어 있다 → 단 왼쪽 '번호 띠'의 잉크 행 = 문항 시작
  - 과목 머리글은 단 중앙의 폭 ~160pt 상자 → 긴 가로선(120~220pt)이 띠 밖에서 시작하면 머리글 상자
  - 단 위쪽에 첫 번호보다 앞선 잉크가 있으면 직전 문항의 이어짐
문항 번호는 읽기 순서로 1부터 부여한다(총 100개가 아니면 실패로 보고).

사용: python tools/extract_scan.py <회차id> "<스캔 문제지.pdf>" [--debug]
"""
import sys, os, io, json
import numpy as np
import pymupdf as fitz
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DPI = 200
K = DPI / 72.0                     # pt → px
TOP_PT, BOT_PT = 146, 1075         # 머리글 밑줄(141pt) 아래부터         # 페이지 머리글/쪽번호 제외 영역(pt)
PAD_TOP, PAD_BOT, PAD_X = 4, 6, 6  # pt


def px(v): return int(round(v * K))


def runs(mask, min_len=1):
    """1차원 bool 배열의 True 구간 [(s,e)] (e exclusive)"""
    out, s = [], None
    for i, v in enumerate(mask):
        if v and s is None: s = i
        if not v and s is not None:
            if i - s >= min_len: out.append((s, i))
            s = None
    if s is not None and len(mask) - s >= min_len: out.append((s, len(mask)))
    return out


def analyze_column(ink, x_lo, x_hi, y_lo, y_hi, debug=False):
    """단 하나(px 좌표)를 분석. 반환: dict(qleft, starts[y_px], headers[(y0,y1)], top_ink, bot_ink, x0, x1)"""
    col = ink[y_lo:y_hi, x_lo:x_hi].copy()
    colsum = col.sum(axis=0)
    # 단 구분 세로선(스캔이 기울면 단 영역 안으로 들어온다): 높이의 40% 이상 이어진 세로 잉크는 지운다
    bad = colsum > 0.4 * (y_hi - y_lo)
    for i in np.where(bad)[0]:
        col[:, max(0, i - 3): i + 4] = False
    colsum = col.sum(axis=0)
    xs = np.where(colsum >= 8)[0]        # 가로줄(표 선 등)의 2~3px 잉크는 무시
    if len(xs) == 0:
        return None
    x0 = x_lo + int(xs[0]); x1 = x_lo + int(xs[-1]) + 1
    ink = ink.copy(); ink[y_lo:y_hi, x_lo:x_hi] = col      # 이후 계산은 세로선 제거본으로
    # 번호 띠: 잉크가 있는 가장 왼쪽 x부터 8pt — 본문 들여쓰기(≈11pt)보다 좁다
    strip = ink[y_lo:y_hi, x0: x0 + px(8)]
    rows = strip.sum(axis=1) > 0
    starts = []
    for s, e in runs(rows):
        h = (e - s) / K
        if 4 <= h <= 14:
            starts.append(y_lo + s)
        elif debug:
            print(f"    띠 잉크 무시 y={(y_lo+s)/K:.0f}pt h={h:.1f}pt")
    # 머리글 상자: 폭 120~220pt 가로선이 띠에서 50pt 이상 떨어진 곳에서 시작
    headers = []
    rowsum_runs = []
    for y in range(y_lo, y_hi):
        r = ink[y, x0:x1]
        for s, e in runs(r, min_len=px(60)):
            if (e - s) <= px(220) and s >= px(50):
                rowsum_runs.append(y)
                break
    for s, e in runs(np.isin(np.arange(y_lo, y_hi), rowsum_runs)):
        pass
    # 가로선 y들을 30pt 이내로 묶어 상자(위선~아래선)로
    box = None
    for y in rowsum_runs:
        if box and y - box[1] < px(40): box[1] = y
        else:
            if box: headers.append(tuple(box))
            box = [y, y]
    if box: headers.append(tuple(box))
    headers = [h for h in headers if 15 <= (h[1] - h[0]) / K <= 45]   # 머리글 상자 높이 15~45pt
    anyrow = np.where(col.sum(axis=1) > 0)[0]
    return dict(x0=x0, x1=x1, starts=starts, headers=headers,
                top_ink=y_lo + int(anyrow[0]), bot_ink=y_lo + int(anyrow[-1]) + 1, y_lo=y_lo, y_hi=y_hi)


def extract(round_id, pdf_path, debug=False):
    doc = fitz.open(pdf_path)
    out_dir = os.path.join(ROOT, "img", round_id)
    os.makedirs(out_dir, exist_ok=True)
    pieces = []      # 읽기 순서의 조각: dict(kind='q'|'cont', page, x0,x1,y0,y1) (px)
    pages_img = {}
    for pno in range(1, len(doc)):
        if len([q for q in pieces if q['kind'] == 'q']) >= 100:
            break
        page = doc[pno]
        pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        pages_img[pno] = arr
        ink = arr < 140
        W = pix.width
        mid = W // 2
        y_lo, y_hi = px(TOP_PT), min(px(BOT_PT), pix.height)
        # 가운데 세로 구분선 제외: mid±6pt는 버린다
        cols = [(px(40), mid - px(6)), (mid + px(6), W - px(40))]
        for ci, (xl, xh) in enumerate(cols):
            c = analyze_column(ink, xl, xh, y_lo, y_hi, debug)
            if not c or not c["starts"]:
                continue
            if debug:
                print(f"p{pno+1} col{ci}: x0={c['x0']/K:.0f}pt starts={[round(s/K) for s in c['starts']]} headers={[(round(a/K),round(b/K)) for a,b in c['headers']]}")
            # 이어짐 조각: 첫 번호 위에 잉크(머리글 상자 아님)
            first = c["starts"][0]
            hdr_above = [h for h in c["headers"] if h[1] <= first]
            top_limit = max([h[1] + px(2) for h in hdr_above], default=c["y_lo"])
            region = ink[top_limit:first - px(1), c["x0"]:c["x1"]]
            rr = np.where(region.sum(axis=1) > 0)[0]
            if len(rr) and not hdr_above:          # 머리글 아래에서 시작하는 단은 이어짐이 아님
                pieces.append(dict(kind="cont", page=pno, x0=c["x0"], x1=c["x1"],
                                   y0=top_limit + int(rr[0]), y1=top_limit + int(rr[-1]) + 1))
            for i, s in enumerate(c["starts"]):
                nxt = c["starts"][i + 1] if i + 1 < len(c["starts"]) else c["y_hi"]
                # 다음 시작 전에 머리글 상자가 있으면 그 위에서 끊는다
                hs = [h for h in c["headers"] if s < h[0] < nxt]
                end = (hs[0][0] - px(3)) if hs else nxt - px(1)
                region = ink[s:end, c["x0"]:c["x1"]]
                rr = np.where(region.sum(axis=1) > 0)[0]
                y1 = s + int(rr[-1]) + 1 if len(rr) else end
                pieces.append(dict(kind="q", page=pno, x0=c["x0"], x1=c["x1"], y0=s, y1=y1))

    # 조각 → 문항 묶기 (번호는 순서대로)
    questions = []
    for p in pieces:
        if p["kind"] == "cont":
            if questions: questions[-1].append(p)
            continue
        questions.append([p])
        if len(questions) == 100:
            pass
    print(f"[{round_id}] 문항 시작 {len(questions)}개 감지 (기대 100)")
    if len(questions) != 100:
        print("  ! 개수가 100이 아니라 저장하지 않음. --debug 로 단별 starts를 확인하세요.")
        return
    texts_out = []
    last = questions[-1][-1]
    arr = pages_img[last["page"]]
    reg = arr[last["y0"]:last["y1"], last["x0"]:last["x1"]] < 140
    gap = 0
    for y in range(reg.shape[0]):
        if reg[y].any(): gap = 0
        else:
            gap += 1
            if gap >= px(30):
                last["y1"] = last["y0"] + y - gap + 1; break
    for n, parts in enumerate(questions, 1):
        imgs = []
        for p in parts:
            arr = pages_img[p["page"]]
            y0 = max(0, p["y0"] - px(PAD_TOP)); y1 = min(arr.shape[0], p["y1"] + px(PAD_BOT))
            x0 = max(0, p["x0"] - px(PAD_X)); x1 = min(arr.shape[1], p["x1"] + px(PAD_X))
            imgs.append(Image.fromarray(arr[y0:y1, x0:x1]).convert("RGB"))
        w = max(im.width for im in imgs); h = sum(im.height for im in imgs)
        canvas = Image.new("RGB", (w, h), "white")
        y = 0
        for im in imgs:
            canvas.paste(im, (0, y)); y += im.height
        canvas.save(os.path.join(out_dir, f"{n:02d}.webp"), "WEBP", quality=82, method=6)
        texts_out.append(dict(n=n, text="", parts=len(parts), w=w, h=h))
    os.makedirs(os.path.join(ROOT, "tools", "text"), exist_ok=True)
    with open(os.path.join(ROOT, "tools", "text", f"{round_id}.json"), "w", encoding="utf-8") as f:
        json.dump(texts_out, f, ensure_ascii=False, indent=1)
    multi = [t["n"] for t in texts_out if t["parts"] > 1]
    print(f"  저장 완료. 이어붙임 {len(multi)}개 {multi}")
    ratios = sorted(((t["h"] / t["w"], t["n"]) for t in texts_out), reverse=True)
    print("  종횡비 상위:", [(n, round(r, 2)) for r, n in ratios[:8]])
    print("  종횡비 하위:", [(n, round(r, 2)) for r, n in ratios[-5:]])


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2], debug="--debug" in sys.argv)
