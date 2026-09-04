# -*- coding: utf-8 -*-
"""tools/answers/*.json + tools/exp/*.json + img/<회차>/NN.webp → data.js
사용: python tools/merge.py
검증: 회차마다 이미지 100장·정답 100개·해설 100개가 전부 있어야 포함한다(부족한 회차는 건너뛰고 경고).
version.json의 data 값을 문항 수로 갱신한다."""
import os, json, glob, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBJECTS = ["기초간호학 개요", "보건간호학 개요", "공중보건학 개요", "실기"]


def main():
    rounds = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "img", "*")) if os.path.isdir(p))
    qs = []
    for r in rounds:
        imgs = {int(os.path.splitext(os.path.basename(p))[0]) for p in glob.glob(os.path.join(ROOT, "img", r, "*.webp"))}
        ap = os.path.join(ROOT, "tools", "answers", f"{r}.json")
        ep = os.path.join(ROOT, "tools", "exp", f"{r}.json")
        if not (os.path.exists(ap) and os.path.exists(ep)):
            print(f"! {r}: 정답({os.path.exists(ap)})/해설({os.path.exists(ep)}) 없음 → 제외"); continue
        ans = {int(k): v for k, v in json.load(open(ap, encoding="utf-8")).items()}
        exp = {e["n"]: e for e in json.load(open(ep, encoding="utf-8"))}
        missing = [n for n in range(1, 101) if n not in imgs or n not in ans or n not in exp]
        if missing:
            print(f"! {r}: 누락 {missing[:10]}{'…' if len(missing) > 10 else ''} → 제외"); continue
        flags = [(n, exp[n]["flag"]) for n in range(1, 101) if exp[n].get("flag")]
        bad = [n for n in range(1, 101) if not (1 <= ans[n]["ans"] <= 5) or ans[n]["subj"] not in SUBJECTS
               or not exp[n].get("topic") or len(exp[n].get("exp", "")) < 60]
        if bad:
            print(f"! {r}: 형식 이상 문항 {bad} → 제외"); continue
        for n in range(1, 101):
            qs.append(dict(id=f"{r}-{n}", r=r, n=n, subj=ans[n]["subj"], topic=exp[n]["topic"].strip(),
                           exp=re.sub(r"\s+", " ", exp[n]["exp"]).strip(), ans=ans[n]["ans"]))
        print(f"{r}: 100문항 OK" + (f"  flag {len(flags)}건: {flags}" if flags else ""))
    data = dict(subjects=SUBJECTS, questions=qs)
    with open(os.path.join(ROOT, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.QUIZ_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    vp = os.path.join(ROOT, "version.json")
    v = json.load(open(vp, encoding="utf-8-sig")) if os.path.exists(vp) else {}
    v["data"] = str(len(qs))
    v.setdefault("note", "index.html의 APP_VERSION과 app 값을 항상 같이 올린다. data.js를 바꾸면 data 값도 함께 올린다.")
    m = re.search(r'const APP_VERSION = "([^"]+)"', open(os.path.join(ROOT, "index.html"), encoding="utf-8").read())
    v["app"] = m.group(1)
    json.dump(v, open(vp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"data.js: {len(qs)}문항 / {len({q['r'] for q in qs})}회차, version.json app={v['app']} data={v['data']}")
    dist = {k: sum(1 for q in qs if q["ans"] == k) for k in range(1, 6)}
    print("정답 분포", dist)


if __name__ == "__main__":
    main()
