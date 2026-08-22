# -*- coding: utf-8 -*-
"""
同济选课助手插件 —— 第 3 课补充：工具职责切分

关键原则：一个工具只负责一件事。
LLM 决定调用哪个工具时，只看工具的名字和描述(docstring)，看不到实现。
所以 search_course 只管"课程名/代码"，search_teacher 只管"教师名"，职责不重叠。
"""
import json
from pathlib import Path

from astrbot import logger
from astrbot.api import star
from astrbot.api.all import llm_tool
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.star.filter.command import GreedyStr


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        index_file = Path(__file__).parent / "courses_index.json"
        if index_file.exists():
            try:
                self.courses = json.loads(index_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"[tongji_course] 索引加载失败: {e}")
                self.courses = []
        else:
            logger.warning("[tongji_course] 未找到 courses_index.json")
            self.courses = []
        logger.info(f"[tongji_course] 插件已加载，共 {len(self.courses)} 门课程")

    # ---------- 命令 ----------
    @filter.command("course")
    async def course(self, event: AstrMessageEvent, keyword: GreedyStr) -> None:
        """查询课程信息。用法：/course 课程名"""
        if not keyword:
            event.set_result("用法：/course 课程名\n例如：/course 高数")
            return
        event.set_result(self._search(keyword))

    # ---------- 工具 1：查课程（只按课程名/代码） ----------
    @llm_tool(name="search_course")
    async def search_course(self, event: AstrMessageEvent, keyword: str) -> str:
        """搜索同济大学的某门课程。按课程名或课程代码查找，返回该课程的基本信息（课程代码、学分、评分、评价数、院系）。

        注意：查询"某位老师教了哪些课"时，请改用 search_teacher 工具。

        Args:
            keyword(string): 课程名或课程代码关键词
        """
        return self._search(keyword)

    # ---------- 工具 2：查教师（只按教师名） ----------
    @llm_tool(name="search_teacher")
    async def search_teacher(self, event: AstrMessageEvent, teacher_name: str) -> str:
        """查询某位同济大学老师开设的课程。输入教师姓名，返回该老师任教的课程列表、学分、评分和评价数。

        Args:
            teacher_name(string): 教师姓名
        """
        return self._search_teacher(teacher_name)

    # ---------- 共用逻辑 ----------
    def _search(self, keyword: str) -> str:
        try:
            if not self.courses:
                return "课程索引未加载：请先运行 build_index.py 生成 courses_index.json 并放入插件目录。"
            kw = (keyword or "").strip().lower()
            if not kw:
                return "请输入要查询的关键词。"
            # 只匹配课程名和课程代码，不再匹配教师名（教师查询归 search_teacher 管）
            hits = [
                c for c in self.courses
                if kw in (c.get("name") or "").lower() or kw in (c.get("code") or "").lower()
            ]
            if not hits:
                return f"没有找到与「{keyword}」相关的课程。"
            hits.sort(key=lambda c: c.get("review_count") or 0, reverse=True)
            top = hits[:5]
            lines = [f"找到 {len(hits)} 门与「{keyword}」相关的课程，评价数最多的 {len(top)} 门："]
            for i, c in enumerate(top, 1):
                lines.append(
                    f"{i}. {c['name']}（代码 {c['code']}）｜教师 {c['teacher_name']}｜"
                    f"学分 {c['credit']}｜评分 {c['rating']}/5｜评价 {c['review_count']} 条｜{c['department']}"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"[tongji_course] search 出错: {e}")
            return f"查询出错：{e}"

    def _search_teacher(self, teacher_name: str) -> str:
        try:
            if not self.courses:
                return "课程索引未加载：请先运行 build_index.py 生成 courses_index.json 并放入插件目录。"
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
        except Exception as e:
            logger.error(f"[tongji_course] search_teacher 出错: {e}")
            return f"查询出错：{e}"
