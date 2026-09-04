# -*- coding: utf-8 -*-
"""가답안 PDF(텍스트 레이어) → tools/answers/<회차>.json  {n: {ans, subj}}
사용: python tools/answers.py <회차id> "<가답안.pdf>"
표 구조: 교시 / 과목 / 문제번호 / 정답 이 줄 단위로 반복된다."""
import sys, os, re, json
import pymupdf as fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBJ = {"기초간호학개요": "기초간호학 개요", "기초간호학 개요": "기초간호학 개요",
        "보건간호학개요": "보건간호학 개요", "보건간호학 개요": "보건간호학 개요",
        "공중보건학개요": "공중보건학 개요", "공중보건학개론": "공중보건학 개요", "공중보건학 개론": "공중보건학 개요", "공중보건학 개요": "공중보건학 개요",
        "실기": "실기"}


def parse(round_id, pdf):
    toks = []
    for p in fitz.open(pdf):
        toks += [t.strip() for t in p.get_text().split("\n") if t.strip()]
    ans = {}
    i = 0
    while i < len(toks) - 3:
        if toks[i] == "1교시" and toks[i + 1] in SUBJ and toks[i + 2].isdigit() and toks[i + 3] in "12345" and len(toks[i + 3]) == 1:
            n = int(toks[i + 2])
            ans[n] = dict(ans=int(toks[i + 3]), subj=SUBJ[toks[i + 1]])
            i += 4
        else:
            i += 1
    missing = sorted(set(range(1, 101)) - set(ans))
    os.makedirs(os.path.join(ROOT, "tools", "answers"), exist_ok=True)
    with open(os.path.join(ROOT, "tools", "answers", f"{round_id}.json"), "w", encoding="utf-8") as f:
        json.dump({str(k): ans[k] for k in sorted(ans)}, f, ensure_ascii=False, indent=1)
    subj_rng = {}
    for n, v in ans.items():
        subj_rng.setdefault(v["subj"], []).append(n)
    print(f"[{round_id}] {len(ans)}개  누락 {missing}  과목범위 {{{', '.join(f'{s}:{min(v)}~{max(v)}' for s, v in subj_rng.items())}}}",
          "정답분포", {k: sum(1 for v in ans.values() if v['ans'] == k) for k in range(1, 6)})


if __name__ == "__main__":
    parse(sys.argv[1], sys.argv[2])
