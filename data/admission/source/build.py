"""schools/<學年度>/*.txt -> ../sieve_programs.csv + ../sieve_steps.csv

資料來源：大學甄選入學委員會「各校系篩選標準一覽表」（篩選結果圖檔，人工轉錄）。
用法：python data/admission/source/build.py

每個 txt 第一行：學校代碼|校名
其餘每行：code|gender|name|quota|檢定(國 英 數A 數B 社 自 英聽)|倍率(國 英 數A 數B 社 自 組合)|篩選順序(逗號分隔，- 表示未篩選)|同級分超額篩選(* 或空白)
"""
import csv, re
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE.parent

SUBJECTS = ["國文", "英文", "數學A", "數學B", "社會", "自然"]
LEVEL = {"頂": "頂標", "前": "前標", "均": "均標", "後": "後標", "底": "底標", "-": ""}
ABBR = {"國": "國文", "英": "英文", "數A": "數學A", "數B": "數學B", "社": "社會", "自": "自然"}


def expand(label):
    """'國英數A自' / '(英文+數學A)' / '數學A' -> ['國文','英文','數學A','自然']"""
    label = label.strip("()")
    if "+" in label:
        parts = label.split("+")
    elif label in SUBJECTS:
        parts = [label]
    else:
        parts = re.findall(r"數[AB]|[國英社自]", label)
        if "".join(parts) != label:
            raise ValueError(f"無法解析科目組合：{label}")
        parts = [ABBR[p] for p in parts]
    for p in parts:
        if p not in SUBJECTS:
            raise ValueError(f"未知科目：{p}（{label}）")
    return parts


programs, steps, seen = [], [], set()
for path in sorted((HERE / "schools").glob("*/*.txt"), key=lambda p: (-int(p.parent.name), p.name)):
    YEAR = int(path.parent.name)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    school_code, school = lines[0].split("|")
    for line in lines[1:]:
        code, gender, name, quota, checks, ratios, seq, tie = line.split("|")
        checks, ratios = checks.split(), ratios.split()
        assert len(checks) == 7 and len(ratios) == 7, line
        assert code.startswith(school_code) and (YEAR, code, gender) not in seen, line
        seen.add((YEAR, code, gender))
        programs.append([YEAR, school_code, school, code, name, gender, int(quota),
                         *[LEVEL[c] for c in checks[:6]], "" if checks[6] == "-" else checks[6],
                         *["" if r == "-" else r for r in ratios],
                         "Y" if tie == "*" else ""])
        if seq == "-":
            continue  # 報名人數未超額，未進行倍率篩選
        for order, item in enumerate(seq.split(","), 1):
            label, score = re.fullmatch(r"(.+?)(\d+)", item).groups()
            subjects = expand(label)
            assert int(score) <= 15 * len(subjects), item
            steps.append([YEAR, code, gender, order, label, "+".join(subjects), len(subjects), int(score)])

HEAD_P = ["year", "school_code", "school", "program_code", "program", "gender", "quota",
          "check_chinese", "check_english", "check_math_a", "check_math_b", "check_social", "check_science", "check_listening",
          "ratio_chinese", "ratio_english", "ratio_math_a", "ratio_math_b", "ratio_social", "ratio_science", "ratio_combo",
          "tie_break_extra"]
HEAD_S = ["year", "program_code", "gender", "step", "label", "subjects", "subject_count", "min_score"]

for name, head, rows in (("sieve_programs.csv", HEAD_P, programs), ("sieve_steps.csv", HEAD_S, steps)):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(rows)

counts = {}
for p in programs:
    counts[(p[0], p[2])] = counts.get((p[0], p[2]), 0) + 1
print(counts, "|", len(programs), "programs,", len(steps), "steps")
