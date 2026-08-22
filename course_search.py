# -*- coding: utf-8 -*-
"""课程数据检索逻辑：加载索引、宽松匹配、单课/教师查询、教师对比聚合。

纯领域逻辑，不依赖 astrbot（只依赖 stdlib），便于单独测试。
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 常见课程简称 → 全称（放宽自然语言关键词匹配）
_COURSE_ABBR = {
    "高数": "高等数学", "线代": "线性代数", "大物": "大学物理", "高代": "高等代数",
    "数分": "数学分析", "概率": "概率论", "离散": "离散数学",
    "毛概": "毛泽东思想和中国特色社会主义理论体系概论", "马原": "马克思主义基本原理",
}
# 口语/噪声词，匹配前去掉
_NOISE = ["有哪些老师", "有哪些", "哪些老师", "的老师", "怎么样", "怎么", "是谁", "什么课", "老师", "课程", "的吗", "啊", "吧"]


class CourseSearch:
    """封装课程索引的加载与检索。"""

    def __init__(self, courses=None, index_path=None):
        if courses is None and index_path is not None:
            with open(Path(index_path), encoding="utf-8") as f:
                courses = json.load(f)
        self.courses = courses or []

    @classmethod
    def load(cls, index_path):
        """从 JSON 索引文件构建。"""
        return cls(index_path=index_path)

    # ---------- 宽松匹配 ----------
    def _clean_kw(self, kw):
        kw = (kw or "").strip().lower()
        for w in _NOISE:
            kw = kw.replace(w, "")
        kw = kw.strip()
        for abbr in sorted(_COURSE_ABBR, key=len, reverse=True):
            if kw.startswith(abbr):
                kw = _COURSE_ABBR[abbr] + kw[len(abbr):]
                break
        return kw.strip()

    def _candidate_kws(self, kw):
        cleaned = self._clean_kw(kw)
        cands = [cleaned]
        for abbr in sorted(_COURSE_ABBR, key=len, reverse=True):
            if cleaned.startswith(abbr):
                cands.append(_COURSE_ABBR[abbr])
                break
        return cands

    def _match_courses(self, kw):
        """返回 (相关度, 课程) 排序列表：子串 + 子序列匹配，处理简称/口语。"""
        candidates = self._candidate_kws(kw)
        scored = []
        for c in self.courses:
            name = (c.get("name") or "").lower()
            code = (c.get("code") or "").lower()
            best = 0
            for cand in candidates:
                if not cand:
                    continue
                s = 0
                if cand == name:
                    s = 100
                elif cand in name:
                    s = 80
                elif cand in code:
                    s = 70
                else:
                    it = iter(name)
                    if all(ch in it for ch in cand):
                        s = 40
                best = max(best, s)
            if best:
                scored.append((best, c))
        scored.sort(key=lambda x: (-x[0], -(x[1].get("review_count") or 0)))
        return scored

    # ---------- 查询 ----------
    def search(self, keyword: str) -> str:
        """查一门课：评分/评价数/教师 + 评价总结 + 学生原话。"""
        if not self.courses:
            return "课程索引未加载：请先生成 courses_index.json 并放入插件目录。"
        kw = self._clean_kw(keyword)
        if not kw:
            return "请输入要查询的关键词。"
        scored = self._match_courses(kw)
        if not scored:
            return f"没有找到与「{keyword}」相关的课程。"
        top = [c for _, c in scored[:5]]
        lines = [f"找到 {len(scored)} 门与「{keyword}」相关的课程："]
        for i, c in enumerate(top, 1):
            lines.append(f"{i}. {c['name']}｜教师 {c['teacher_name']}｜评分 {c['rating']}/5｜评价 {c['review_count']} 条")
            if c.get("summary"):
                lines.append(f"   评价总结：{c['summary']}")
            for s in (c.get("samples") or [])[:3]:
                cm = (s.get("c") or "").strip()
                if cm:
                    lines.append(f"   学生原话：{cm[:80]}")
        return "\n".join(lines)

    def search_teacher(self, teacher_name: str) -> str:
        """查某位老师开了哪些课。"""
        if not self.courses:
            return "课程索引未加载：请先生成 courses_index.json 并放入插件目录。"
        tn = (teacher_name or "").strip()
        if not tn:
            return "请输入教师姓名。"
        hits = [c for c in self.courses if tn in (c.get("teacher_name") or "")]
        if not hits:
            return f"没有找到教师「{teacher_name}」的任课记录。"
        hits.sort(key=lambda c: c.get("review_count") or 0, reverse=True)
        top = hits[:5]
        lines = [f"教师「{tn}」共开设 {len(hits)} 门课，评价数最多的 {len(top)} 门："]
        for i, c in enumerate(top, 1):
            lines.append(
                f"{i}. {c['name']}（代码 {c['code']}）｜学分 {c['credit']}｜评分 {c['rating']}/5｜评价 {c['review_count']} 条"
            )
        return "\n".join(lines)

    def build_teacher_rows(self, course_name: str):
        """按课程聚合各任课老师的评分/评价数/总结/样例。

        返回 (rows, display_name)；找不到则返回错误字符串。
        """
        if not self.courses:
            return "课程索引未加载。"
        kw = self._clean_kw(course_name)
        if not kw:
            return "请输入课程名。"
        scored = self._match_courses(kw)
        if not scored:
            kwraw = (course_name or "").strip().lower()
            matched = [c for c in self.courses if kwraw in (c.get("teacher_name") or "").lower()]
        else:
            top_score = scored[0][0]
            matched = [c for s, c in scored if s >= top_score]
        if not matched:
            return f"没有找到课程「{course_name}」。"
        groups = {}
        for c in matched:
            tn = c.get("teacher_name") or "未知教师"
            g = groups.setdefault(tn, {"rs": 0.0, "w": 0, "review_count": 0, "samples": [], "best": (0, "")})
            cnt = c.get("review_count") or 0
            r = c.get("rating") or 0
            g["rs"] += r * max(cnt, 1)
            g["w"] += max(cnt, 1)
            g["review_count"] += cnt
            for s in (c.get("samples") or [])[:2]:
                if len(g["samples"]) < 4:
                    g["samples"].append(s)
            if c.get("summary") and cnt >= g["best"][0]:
                g["best"] = (cnt, c["summary"])
        rows = []
        for tn, g in groups.items():
            rating = round(g["rs"] / g["w"], 2) if g["w"] else 0
            rows.append({"teacher": tn, "rating": rating, "review_count": g["review_count"],
                         "samples": g["samples"], "summary": g["best"][1]})
        rows.sort(key=lambda r: r["review_count"], reverse=True)
        return rows, matched[0]["name"]
