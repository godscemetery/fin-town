# -*- coding: utf-8 -*-
"""
测试任务分解（task decomposition）是否能在 qwen3-max 下正常运行。
运行方式（在 backend_server 下执行）：

(smallville) > python test_task_decomp.py
"""

import os
import sys
import datetime

# === 1. 设置路径 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# === 2. 导入我们要测试的函数 ===
from persona.prompt_template.run_gpt_prompt import run_gpt_prompt_task_decomp


# === 3. 构造最小可运行 Persona/Scratch ===
class FakeScratch:
    """
    任务分解模块依赖：
      - name
      - get_str_firstname()
      - get_str_iss()
      - curr_time
      - f_daily_schedule_hourly_org
      - f_daily_schedule_hourly_org_index
    这些都造一个最小实现即可。
    """

    def __init__(self):
        self.name = "Klaus Mueller"
        self.iss = "hardworking, detail-oriented, values productivity"

        # 当前时间（随便给一个）
        self.curr_time = datetime.datetime(2025, 1, 1, 9, 0, 0)

        # 一个极简的“原始 schedule”，每项是 (任务名, 时长分钟)
        # 例如：睡觉 6 小时 → (sleeping, 360)
        self.f_daily_schedule_hourly_org = [
            ["sleeping", 360],
            ["morning routine", 60],
            ["breakfast", 60],
            ["work", 240],
        ]

        # 假设当前处于第 1 段（morning routine）
        self._org_index = 1

    # === 小镇框架需要的一些接口 ===
    def get_str_iss(self):
        return self.iss

    def get_str_firstname(self):
        return self.name.split()[0]

    def get_f_daily_schedule_hourly_org_index(self):
        return self._org_index


class FakePersona:
    def __init__(self):
        self.scratch = FakeScratch()
        # 给 task_decomp 那边用的名字字段
        self.name = self.scratch.name

    # 有的地方可能会用到 get_str_name()，顺手加一个保险
    def get_str_name(self):
        return self.name



# === 4. 写测试函数 ===
def test_decomp(task="clean the house", duration=60):
    """
    用一个任务（task）和任务总时长（duration）来测试任务分解逻辑。
    """
    persona = FakePersona()

    print("\n===== TEST TASK DECOMP =====")
    print(f"Task: {task}")
    print(f"Duration: {duration} minutes")

    # 运行任务分解
    output, debug_info = run_gpt_prompt_task_decomp(
        persona,
        task,
        duration,
        verbose=True
    )

    print("\n===== RAW OUTPUT =====")
    print(output)

    print("\n===== CHECK TOTAL MINUTES =====")
    total = sum(item[1] for item in output)
    print(f"Sum of durations = {total} (expected {duration})")

    if total != duration:
        print("⚠ WARNING: total minutes mismatch!")
    else:
        print("✔ duration OK")

    print("\n===== BREAKDOWN =====")
    for subt, mins in output:
        print(f" - {subt}: {mins} min")


# === 5. 主入口 ===
if __name__ == "__main__":
    # 测试示例任务
    test_decomp("clean the house", 60)
    test_decomp("prepare lunch", 45)
    test_decomp("finish school homework", 90)
