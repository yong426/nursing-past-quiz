# -*- coding: utf-8 -*-
"""가답안이 표준 표 PDF가 아닌 회차용.
  python tools/answers_misc.py table2020 <회차id> "<문제지 완성본.pdf>"   # 마지막 쪽 정답표(1~10 / ①…⑤ 반복)
  python tools/answers_misc.py ocr <회차id> "<가답안 스캔.pdf>"          # 이미지 가답안 → rapidocr
과목 구분은 공식 배분(1~35 기초 / 36~50 보건 / 51~70 공중 / 71~100 실기)으로 채운다."""
import sys, os, re, json, io
import pymupdf as fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIRC = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}


def subj_of(n):
    return "기초간호학 개요" if n <= 35 else "보건간호학 개요" if n <= 50 else "공중보건학 개요" if n <= 70 else "실기"


def save(round_id, ans):
    missing = sorted(set(range(1, 101)) - set(ans))
    os.makedirs(os.path.join(ROOT, "tools", "answers"), exist_ok=True)
    with open(os.path.join(ROOT, "tools", "answers", f"{round_id}.json"), "w", encoding="utf-8") as f:
        json.dump({str(k): dict(ans=ans[k], subj=subj_of(k)) for k in sorted(ans)}, f, ensure_ascii=False, indent=1)
    print(f"[{round_id}] {len(ans)}개  누락 {missing}  정답분포", {k: sum(1 for v in ans.values() if v == k) for k in range(1, 6)})


def table2020(round_id, pdf):
    toks = [t.strip() for t in fitz.open(pdf)[-1].get_text().split("\n") if t.strip()]
    ans, i = {}, 0
    while i < len(toks):
        if re.fullmatch(r'\d+', toks[i]) and int(toks[i]) <= 100:
            nums = []
            while i < len(toks) and re.fullmatch(r'\d+', toks[i]):
                nums.append(int(toks[i])); i += 1
            vals = []
            while i < len(toks) and toks[i] in CIRC:
                vals.append(CIRC[toks[i]]); i += 1
            if len(nums) == len(vals):
                ans.update(zip(nums, vals))
            else:
                print("  ! 행 길이 불일치", nums, vals)
        else:
            i += 1
    save(round_id, ans)


def ocr(round_id, pdf):
    from rapidocr_onnxruntime import RapidOCR
    from PIL import Image
    import numpy as np
    eng = RapidOCR()
    ans = {}
    for page in fitz.open(pdf):
        pix = page.get_pixmap(dpi=200)
        img = np.array(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        res, _ = eng(img)
        cells = []
        for box, txt, sc in (res or []):
            ys = [p[1] for p in box]; xs = [p[0] for p in box]
            cells.append(((min(ys) + max(ys)) / 2, min(xs), txt.strip()))
        cells.sort()
        rows, cur = [], []
        for c in cells:
            if cur and abs(c[0] - cur[-1][0]) > 14:
                rows.append(cur); cur = []
            cur.append(c)
        if cur: rows.append(cur)
        for r in rows:
            r.sort(key=lambda c: c[1])
            digits = [re.sub(r'\D', '', c[2]) for c in r]
            digits = [d for d in digits if d]
            # 기대 형태: [..., 문제번호, 정답]  (교시 '1교시'의 1은 제거)
            if len(digits) >= 2 and digits[-1] in "12345" and len(digits[-1]) == 1 and digits[-2].isdigit() and 1 <= int(digits[-2]) <= 100:
                n = int(digits[-2])
                if n in ans and ans[n] != int(digits[-1]):
                    print("  ! 충돌", n, ans[n], digits[-1])
                ans[n] = int(digits[-1])
    save(round_id, ans)


if __name__ == "__main__":
    {"table2020": table2020, "ocr": ocr}[sys.argv[1]](sys.argv[2], sys.argv[3])
