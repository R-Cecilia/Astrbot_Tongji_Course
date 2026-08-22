# -*- coding: utf-8 -*-
"""
同济选课助手插件 —— 入口（命令/工具注册）。

分层设计：
  main.py          本文件：插件入口，注册命令与工具（薄层）
  course_search.py 领域逻辑：加载索引、检索、教师对比聚合
  table_render.py  表现层：深科技表格图片 / 文字渲染

命令（手动）：/course /teacher /compare /cmds
工具（Agent）：search_course / search_teacher / compare_teachers
"""
import base64
from pathlib import Path

from astrbot import logger
from astrbot.api import star
from astrbot.api.all import llm_tool
from astrbot.api.event import AstrMessageEvent, filter, MessageChain, MessageEventResult
from astrbot.core.star.filter.command import GreedyStr

from .course_search import CourseSearch
from .table_render import render_teacher_table, teacher_rows_to_text


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        self.context = context
        index_file = Path(__file__).parent / "courses_index.json"
        try:
            self.service = CourseSearch.load(index_file)
        except Exception as e:
            logger.error(f"[tongji_course] 索引加载失败: {e}")
            self.service = CourseSearch()
        logger.info(f"[tongji_course] 插件已加载，共 {len(self.service.courses)} 门课程")

    # ================= 命令（手动，100% 触发） =================
    @filter.command("course")
    async def course(self, event: AstrMessageEvent, keyword: GreedyStr) -> None:
        """查询课程信息。用法：/course 课程名"""
        if not keyword:
            event.set_result("用法：/course 课程名\n例如：/course 高数")
            return
        event.set_result(self.service.search(keyword))

    @filter.command("teacher")
    async def teacher(self, event: AstrMessageEvent, teacher_name: GreedyStr) -> None:
        """查询某位老师开设的课程。用法：/teacher 老师名"""
        if not teacher_name:
            event.set_result("用法：/teacher 老师名\n例如：/teacher 林胤榜")
            return
        event.set_result(self.service.search_teacher(teacher_name))

    @filter.command("compare")
    async def compare(self, event: AstrMessageEvent, course_name: GreedyStr) -> None:
        """老师对比（输出图片）。用法：/compare 课程名"""
        if not course_name:
            event.set_result("用法：/compare 课程名\n例如：/compare 高等数学(B)上")
            return
        await self._send_compare(event, course_name)

    @filter.command("cmds")
    async def cmds(self, event: AstrMessageEvent) -> None:
        """本插件命令一览（避开官方 /help）。"""
        event.set_result(
            "本插件命令：\n"
            "/course <课程名>    查一门课（评分/教师/评价）\n"
            "/teacher <老师名>   查一位老师开了哪些课\n"
            "/compare <课程名>   对比同一门课的各老师（出图片）\n"
            "\n"
            "提示：也可直接自然语言提问，Agent 会自动调用工具。\n"
            "官方帮助请用 /help"
        )

    # ================= 工具（Agent 自动调用） =================
    @llm_tool(name="search_course")
    async def search_course(self, event: AstrMessageEvent, keyword: str) -> str:
        """查【某门课】的评分、评价数、教师及学生评价。仅当问题针对"某门课"一个对象、且不是要比较多位老师时用。

        Args:
            keyword(string): 课程名或课程代码
        """
        return self.service.search(keyword)

    @llm_tool(name="search_teacher")
    async def search_teacher(self, event: AstrMessageEvent, teacher_name: str) -> str:
        """查【某一位老师】开了哪些课、评分如何。仅当问题针对"单个老师"、且不是要在多位老师之间选/比较时用。

        Args:
            teacher_name(string): 教师姓名
        """
        return self.service.search_teacher(teacher_name)

    @llm_tool(name="compare_teachers")
    async def compare_teachers(self, event: AstrMessageEvent, course_name: str):
        """【比较/选择多位老师】。生成一张"同一门课各任课老师的评分+评价对比表"图片。当用户是在"选/比较老师"（"这个课老师怎么选""几位老师哪个更好""张三和李四选谁"）时调用。

        Args:
            course_name(string): 课程名或课程代码；若用户直接给了老师名，也可传老师名
        """
        result = self.service.build_teacher_rows(course_name)
        if isinstance(result, str):
            yield result                       # 没找到 → 返回文字给 LLM
            return
        rows, display_name = result
        try:
            img_bytes = render_teacher_table(display_name, rows)
        except Exception as e:
            logger.error(f"[tongji_course] compare_teachers 生成图片失败: {e}")
            yield teacher_rows_to_text(display_name, rows)
            return
        # ① 先把图片发给用户（框架一次性发送，不刷屏）
        yield (MessageEventResult()
               .base64_image(base64.b64encode(img_bytes).decode())
               .message(f"\n「{display_name}」任课老师对比，评价为历史数据，仅供参考。"))
        # ② 再给 LLM 一句文字总结，供它组织回答
        best = rows[0] if rows else {}
        yield (f"已生成「{display_name}」任课老师对比表图片。"
               f"评价最多的是 {best.get('teacher')}（评分 {best.get('rating')}/5，评价 {best.get('review_count')} 条）。")

    # ================= 辅助 =================
    async def _send_compare(self, event: AstrMessageEvent, course_name: str) -> None:
        """/compare 命令：构建数据→渲染图片→发送（或文字兜底）。"""
        result = self.service.build_teacher_rows(course_name)
        if isinstance(result, str):
            event.set_result(result)
            return
        rows, display_name = result
        try:
            img_bytes = render_teacher_table(display_name, rows)
        except Exception as e:
            logger.error(f"[tongji_course] /compare 渲染失败: {e}")
            event.set_result(teacher_rows_to_text(display_name, rows))
            return
        try:
            await event.send(
                MessageChain()
                .base64_image(base64.b64encode(img_bytes).decode())
                .message(f"\n「{display_name}」任课老师对比，评价为历史数据，仅供参考。")
            )
        except Exception as e:
            logger.error(f"[tongji_course] /compare 发图失败: {e}")
            event.set_result(teacher_rows_to_text(display_name, rows))
