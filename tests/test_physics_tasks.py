# -*- coding: utf-8 -*-
import asyncio
from _bootstrap import tb
from html.parser import HTMLParser

class C(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.problems = []
    def handle_starttag(self, tag, attrs): self.stack.append(tag)
    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag: self.problems.append(tag)
        else: self.stack.pop()

def check_html(text):
    c = C(); c.feed(text)
    assert not c.stack and not c.problems, (text[:200], c.stack, c.problems)

class FakeUser:
    def __init__(self, uid):
        self.id = uid

class FakeMsg:
    def __init__(self):
        self.edits = []
    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self
    async def delete(self):
        pass
    async def answer(self, text, **kwargs):
        self.edits.append((text, kwargs.get("reply_markup")))
        return self

class FakeCB:
    def __init__(self, data, uid=111222333):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg()
    async def answer(self, text=None, show_alert=False):
        pass

async def main():
    # structural sanity: unique, contiguous task numbers per topic; every field HTML-balanced
    for topic_num, topic in tb.PHYSICS_TASKS.items():
        nums = [t["num"] for t in topic["tasks"]]
        assert nums == sorted(nums) and len(nums) == len(set(nums)), (topic_num, nums)
        assert nums == list(range(1, len(nums) + 1)), (topic_num, nums)
        for task in topic["tasks"]:
            for field in ("title", "condition", "solution"):
                check_html(task[field])
    print("all topics structurally sound, HTML balanced: OK")

    total = sum(len(t["tasks"]) for t in tb.PHYSICS_TASKS.values())
    assert total == 69, total
    print(f"total task count = {total}: OK")

    # spot-check a handful of the 20 tasks added from the 4 uploaded exam tickets
    expected = [
        ("1", 6, "374"),
        ("1", 9, "140"),
        ("2", 6, "580"),
        ("4", 4, "45"),
        ("4", 7, "2 с"),
        ("5", 8, "16 А"),
        ("6", 8, "5</b>"),
        ("7", 6, "230"),
        ("8", 7, "81"),
        ("8", 8, "176"),
        ("9", 7, "131"),
        ("9", 9, "5 см"),
    ]
    for topic_num, num, expect_fragment in expected:
        task = next(t for t in tb.PHYSICS_TASKS[topic_num]["tasks"] if t["num"] == num)
        assert expect_fragment in task["solution"], (topic_num, num, task["solution"])
    print("spot-checked new tasks' numeric answers: OK")

    # handler renders one of the new tasks correctly end-to-end
    cb = FakeCB("phystask_show:9:8")
    await tb.cb_phystask_show(cb)
    text, kb = cb.message.edits[0]
    check_html(text)
    assert "Задача №8" in text
    assert "гамма-излучения" in text
    assert "9 см" in text
    print("phystask_show renders a new task: OK")

    print("ALL PHYSICS TASKS TESTS PASSED")

asyncio.run(main())
