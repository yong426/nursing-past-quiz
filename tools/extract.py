# -*- coding: utf-8 -*-
"""
간호조무사 국가시험 문제지 PDF → 문항별 WebP 크롭 + 문항 텍스트 JSON.

사용:  python tools/extract.py <회차id> "<문제지.pdf>"
  예)  python tools/extract.py 2022-1 "...\2022년도 상반기 ... 문제지(홀수형).pdf"

지원 규격
  - 국시원 공식 A3 2단(842x1191pt, 1쪽 표지, 마지막 쪽 응시자 안내사항) — 텍스트 레이어
  - 한글(HWP)에서 PDF로 저장한 A4 2단(595x841pt) — 텍스트 레이어 (2020하·2024하)
  - 스캔 이미지(텍스트 레이어 없음) — rapidocr로 줄 좌표를 잡아 같은 로직 적용 (2024상)

문항 경계 = 단(column) 왼쪽 여백에 붙은 "N." 줄. 과목 머리글(보건간호학 개요 …)도 경계.
단 끝에서 잘린 문항은 다음 단 위쪽 조각을 이어붙여 한 장으로 만든다. 100번 이후는 무시.

산출: img/<회차>/NN.webp, tools/text/<회차>.json ([{n, text, parts, w, h}])
검수: 출력되는 '종횡비 상위'를 눈으로 확인할 것 — 인접 문항이 붙은 크롭은 종횡비가 튄다.
"""
import sys, os, re, json, io
import pymupdf as fitz
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DPI = 200
OCR_DPI = 200
PAD_TOP, PAD_BOT, PAD_X = 4, 6, 6
Q_RE = re.compile(r'^\s*(\d{1,3})\.(?!\d)')
SUBJ_RE = re.compile(r'^\s*(기초간호학\s*개[요오론]|보건간호학\s*개[요오론]|공중보건학\s*개[요오론]|실\s*기)\s*$')
HEADER_RE = re.compile(r'(간호조무사\s*국가시험|^홀수형$|^짝수형$|^\d+\s*/\s*\d+$|^-\s*\d+\s*-$|'
                       r'각 문제에서 가장 적합한|실전 모의고사|응시자 안내사항)')
EXCLUDE_RE = re.compile(r'^\s*(\d교시|종료|뒷면의 응시자 안내사항.*)\s*$')   # 100번 뒤 '1교시 종료' 표시
NOTICE_RE = re.compile(r'공개일시|이의신청|합격자 발표|자격증 발급|공개장소')
FOOTER_RE = re.compile(r'^\s*(\d+\s*/\s*\d+|-\s*\d+\s*-)\s*$')   # 쪽번호만 푸터로 본다
_ocr = None


def ocr_lines(page):
    """텍스트 레이어가 없는 스캔 페이지: rapidocr로 줄 박스를 얻어 pt 좌표로 돌려준다."""
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    pix = page.get_pixmap(dpi=OCR_DPI)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    import numpy as np
    res, _ = _ocr(np.array(img))
    k = 72.0 / OCR_DPI
    out = []
    for box, txt, score in (res or []):
        xs = [p[0] for p in box]; ys = [p[1] for p in box]
        out.append((min(xs) * k, min(ys) * k, max(xs) * k, max(ys) * k, txt.strip()))
    return out


def page_lines(page):
    """텍스트 라인 목록 [(x0,y0,x1,y1,text)]."""
    out = []
    d = page.get_text("dict")
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        for l in b["lines"]:
            txt = "".join(s["text"] for s in l["spans"]).strip()
            if not txt:
                continue
            x0, y0, x1, y1 = l["bbox"]
            out.append((x0, y0, x1, y1, txt))
    if len(out) < 5:          # 스캔 페이지
        out = ocr_lines(page)
    return out


def looks_like_answer_table(lines):
    """마지막 쪽 정답표(숫자/①~⑤만 나열)를 이어짐 조각으로 오인하지 않게."""
    short = [l for l in lines if re.fullmatch(r'[\d①②③④⑤\s]+', l[4])]
    return len(lines) >= 10 and len(short) / len(lines) > 0.7


def extract(round_id, pdf_path):
    doc = fitz.open(pdf_path)
    W = doc[0].rect.width
    mid = W / 2
    out_dir = os.path.join(ROOT, "img", round_id)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "tools", "text"), exist_ok=True)

    # 1) 페이지 → 단(column) 목록 (읽기 순서)
    columns = []
    for pno in range(len(doc)):
        page = doc[pno]
        H = page.rect.height
        lines = page_lines(page)
        body = [l for l in lines if not HEADER_RE.search(l[4])]
        if not body:
            continue
        hdr = [l for l in lines if HEADER_RE.search(l[4]) and l[1] < H * 0.12 and '각 문제에서' not in l[4]]
        ftr = [l for l in lines if FOOTER_RE.match(l[4]) and l[1] > H * 0.85]
        bot_limit = min([l[1] for l in ftr], default=H) - 2
        # 머리글 아래부터 본문. 단, HWP 변환본(2024하)은 머리글이 왼쪽 위에만 있고 오른쪽 단 본문이 같은 높이에서
        # 시작하므로, 그 단에 머리글보다 위/같은 높이의 본문 줄이 있으면 그 단은 자기 단의 머리글만 적용한다.
        glob_top = max([l[3] for l in hdr], default=0) + 2
        def col_top(col):
            own = max([l[3] for l in hdr if ((l[0] + l[2]) / 2 < mid) == (col == 0)], default=0) + 2
            above = [l for l in body if (l[0] < mid) == (col == 0) and own <= l[1] < glob_top]
            return own if above else glob_top
        top_limits = {0: col_top(0), 1: col_top(1)}
        top_limit = min(top_limits.values())
        body = [l for l in body if l[1] >= top_limits[0 if l[0] < mid else 1] and l[3] <= bot_limit
                and not EXCLUDE_RE.match(l[4])]
        gfx = []
        for dr in page.get_drawings():
            r = dr["rect"]
            if r.width < 3 and r.height > 60:        # 단 구분선·페이지 테두리 같은 세로 규칙선
                continue
            if r.y0 >= top_limit and r.y1 <= bot_limit and r.height < H * 0.7 and r.width < W * 0.6:
                gfx.append((r.x0, r.y0, r.x1, r.y1))
        for im in page.get_image_info():
            r = fitz.Rect(im["bbox"])
            if r.y0 >= top_limit and r.y1 <= bot_limit and r.height < H * 0.7:
                gfx.append((r.x0, r.y0, r.x1, r.y1))
        for col in (0, 1):
            cl = [l for l in body if (l[0] < mid) == (col == 0)]
            if not cl:
                continue
            cg = [g for g in gfx if ((g[0] + g[2]) / 2 < mid) == (col == 0) and (g[2] - g[0]) < mid
                  and not (g[0] < mid - 15 and g[2] > mid + 15)          # 단 경계를 가로지르는 도형(머리글 밑줄 등) 제외
                  and g[1] >= top_limits[col]]
            # 단 왼쪽 여백: 문항번호 줄들의 x0 중 최소 (본문 들여쓰기보다 왼쪽)
            qx = [l[0] for l in cl if Q_RE.match(l[4])]
            left = min(qx) if qx else min(l[0] for l in cl)
            left = min(left, min(l[0] for l in cl))
            right = max(l[2] for l in cl)
            qleft = min(qx) if qx else left
            if cg:
                left = max(min(left, min(g[0] for g in cg)), qleft - 30)   # 도형이 단 밖으로 크게 나가면 무시
                right = max(right, max(g[2] for g in cg))
            bounds = []
            for l in cl:
                m = Q_RE.match(l[4])
                if m and l[0] < qleft + 14:
                    bounds.append((l[1], int(m.group(1)), l))
                elif SUBJ_RE.match(l[4]):
                    bounds.append((l[1], None, l))
            bounds.sort()
            columns.append(dict(page=pno, col=col, top=top_limits[col], bot=bot_limit,
                                x0=left, x1=right, lines=cl, gfx=cg, bounds=bounds))

    # 2) 단 → 세그먼트 (경계 사이 구간). "cont" = 단 위쪽의 앞 문항 이어짐, "subj" = 과목 머리글
    segs = []
    for c in columns:
        ys = [b[0] for b in c["bounds"]]
        first_y = ys[0] if ys else c["bot"]
        head_lines = [l for l in c["lines"] if l[1] < first_y - 1]
        head_gfx = [g for g in c["gfx"] if g[1] < first_y - 1]
        if head_lines and not looks_like_answer_table(head_lines):
            y0 = min([l[1] for l in head_lines] + [g[1] for g in head_gfx])
            y1 = max([l[3] for l in head_lines] + [g[3] for g in head_gfx])
            segs.append(dict(q="cont", page=c["page"], col=c["col"], x0=c["x0"], x1=c["x1"], y0=y0, y1=y1,
                             texts=[l[4] for l in head_lines]))
        for i, (y, qn, line) in enumerate(c["bounds"]):
            ny = c["bounds"][i + 1][0] if i + 1 < len(c["bounds"]) else c["bot"] + 1
            ls = [l for l in c["lines"] if y - 1 <= l[1] < ny - 1]
            ty1 = max(l[3] for l in ls)
            gs = [g for g in c["gfx"] if y - 1 <= g[1] < ny - 1 and g[1] <= ty1 + 20]
            y1 = max([ty1] + [g[3] for g in gs])
            segs.append(dict(q=qn if qn is not None else "subj", page=c["page"], col=c["col"], x0=c["x0"], x1=c["x1"],
                             y0=y, y1=y1, texts=[l[4] for l in ls]))

    # 3) 문항별 조각 묶기
    questions, order, last_q = {}, [], None
    for s in segs:
        if 100 in questions and s["q"] != "cont":
            break
        if s["q"] == "subj":
            last_q = None
            continue
        if s["q"] == "cont":
            if any(NOTICE_RE.search(t) for t in s["texts"]):     # 응시자 안내사항 페이지
                continue
            if last_q is None:
                if any(len(t) > 6 for t in s["texts"]):
                    print(f"  ! 이어짐 조각인데 직전 문항 없음 p{s['page']+1} y{s['y0']:.0f}: {s['texts'][:2]}")
                continue
            questions[last_q]["parts"].append(s)
            continue
        qn = s["q"]
        if qn in questions:
            print(f"  ! 문항 {qn} 중복 감지 p{s['page']+1}")
            qn = f"{qn}_dup"
        questions[qn] = dict(parts=[s])
        order.append(qn)
        last_q = qn

    # 4) 렌더 + 저장
    texts_out = []
    for qn in order:
        if not isinstance(qn, int):
            continue
        parts = questions[qn]["parts"]
        imgs = []
        for p in parts:
            page = doc[p["page"]]
            clip = fitz.Rect(p["x0"] - PAD_X, p["y0"] - PAD_TOP, p["x1"] + PAD_X, p["y1"] + PAD_BOT) & page.rect
            # 단 구분 세로선이 크롭에 들어오지 않게 단 경계에서 3pt 안쪽으로 자른다
            if p["col"] == 0: clip.x1 = min(clip.x1, mid - 3)
            else: clip.x0 = max(clip.x0, mid + 3)
            pix = page.get_pixmap(dpi=DPI, clip=clip)
            imgs.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        w = max(im.width for im in imgs); h = sum(im.height for im in imgs)
        canvas = Image.new("RGB", (w, h), "white")
        y = 0
        for im in imgs:
            canvas.paste(im, (0, y)); y += im.height
        canvas.save(os.path.join(out_dir, f"{qn:02d}.webp"), "WEBP", quality=82, method=6)
        texts_out.append(dict(n=qn, text="\n".join(t for p in parts for t in p["texts"]),
                              parts=len(parts), w=w, h=h))
    with open(os.path.join(ROOT, "tools", "text", f"{round_id}.json"), "w", encoding="utf-8") as f:
        json.dump(texts_out, f, ensure_ascii=False, indent=1)

    nums = sorted(q for q in order if isinstance(q, int))
    missing = sorted(set(range(1, 101)) - set(nums))
    extra = [q for q in order if not isinstance(q, int)]
    multi = [t["n"] for t in texts_out if t["parts"] > 1]
    print(f"[{round_id}] {len(nums)}문항  누락 {missing}  중복 {extra}  이어붙임 {len(multi)}개 {multi}")
    ratios = sorted(((t["h"] / t["w"], t["n"]) for t in texts_out), reverse=True)
    print("  종횡비 상위:", [(n, round(r, 2)) for r, n in ratios[:8]])
    print("  종횡비 하위:", [(n, round(r, 2)) for r, n in ratios[-5:]])


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2])
