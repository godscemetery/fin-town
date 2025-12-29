"""
Author: Joon Sung Park (joonspk@stanford.edu)

File: execute.py
Description: This defines the "Act" module for generative agents. 
"""
import sys
import random
sys.path.append('../../')

from global_methods import *
from path_finder import *
from utils import *

# === 新闻行为钩子：在执行阶段触发读新闻并写入记忆 ===
try:
  # 标准包导入（推荐）
  from persona.news.news_action import run_read_news_action
except Exception:
  # 兜底导入（避免某些运行方式下包路径不一致）
  run_read_news_action = None

# === 交易行为钩子：在执行阶段触发交易决策/下单并写入记忆 ===
try:
  from persona.trade.trade_action import run_trade_action
except Exception:
  run_trade_action = None


def clean_plan_address(plan: str):
    """
    清洗 LLM 生成的地址字符串，使之能对应 maze.address_tiles 的 key。
    支持以下情况：
      - 去掉 {...}
      - 去掉 <random> / <something>
      - 只保留 world:sector:arena 三段
      - 去掉多余的空格
    """
    raw = str(plan).strip()

    # 去掉花括号 { }
    cleaned = raw.replace("{", "").replace("}", "").strip()

    # 去掉 <xxxx>
    if "<" in cleaned:
        cleaned = cleaned.split("<")[0].strip()

    # 只保留前三段 world : sector : arena
    parts = cleaned.split(":")
    if len(parts) >= 3:
        cleaned_key = ":".join(parts[:3]).strip()
    else:
        cleaned_key = cleaned.strip()

    return cleaned_key

def execute(persona, maze, personas, plan): 
  """
  Given a plan (action's string address), we execute the plan (actually 
  outputs the tile coordinate path and the next coordinate for the 
  persona). 

  INPUT:
    persona: Current <Persona> instance.  
    maze: An instance of current <Maze>.
    personas: A dictionary of all personas in the world. 
    plan: This is a string address of the action we need to execute. 
       It comes in the form of "{world}:{sector}:{arena}:{game_objects}". 
       It is important that you access this without doing negative 
       indexing (e.g., [-1]) because the latter address elements may not be 
       present in some cases. 
       e.g., "dolores double studio:double studio:bedroom 1:bed"
    
  OUTPUT: 
    execution
  """

  # =========================================================
  # [新增] 新闻读取钩子：当当前动作描述包含 news 时，读一条新闻写入 a_mem
  # - 用 scratch._news_action_last_sig 去重，避免同一动作持续期间重复触发
  # - 永不影响主流程：任何异常仅打印 warning
  # =========================================================
  try:
    scratch = persona.scratch

    act_desc = getattr(scratch, "act_description", "") or ""
    if not act_desc:
      act_desc = getattr(scratch, "act", "") or ""
    if not act_desc:
      act_desc = getattr(scratch, "curr_action", "") or ""

    act_desc_l = act_desc.lower() if isinstance(act_desc, str) else ""

    # ✅ 关键：只在“动作刚开始”触发一次（act_path_set 还没置 True）
    is_new_action_tick = (getattr(scratch, "act_path_set", False) is False)

    if is_new_action_tick and (("news" in act_desc_l) or ("newspaper" in act_desc_l)):
      # 用 act_desc + act_address 做动作级去重（不再用 curr_time 做粒度）
      act_addr = getattr(scratch, "act_address", "") or ""
      sig = (act_desc_l, act_addr)

      last_sig = getattr(scratch, "_news_action_last_sig", None)
      if last_sig != sig:
        curr_time = getattr(scratch, "curr_time", None)
        if run_read_news_action is not None:
          res = run_read_news_action(persona, now=curr_time)
          scratch._news_action_last_sig = sig
          scratch._news_action_last_result = res
        else:
          print("WARNING: run_read_news_action not available; skip news action.")
  except Exception as e:
    print("WARNING: news action hook error:", e)

  # =========================================================
  # [新增] 交易钩子：当当前动作描述包含 trade/market 等时，触发交易模块
  # - 用 scratch.trade_trigger_cache 去重（按天清空）
  # - 永不影响主流程：任何异常仅打印 warning
  # =========================================================
  try:
    scratch = persona.scratch

    act_desc = getattr(scratch, "act_description", "") or ""
    if not act_desc:
      act_desc = getattr(scratch, "act", "") or ""
    if not act_desc:
      act_desc = getattr(scratch, "curr_action", "") or ""

    act_desc_l = act_desc.lower() if isinstance(act_desc, str) else ""

    hit_trade = (
      ("trade" in act_desc_l) or ("trading" in act_desc_l) or
      ("market" in act_desc_l) or ("portfolio" in act_desc_l) or
      ("buy" in act_desc_l) or ("sell" in act_desc_l)
    )

    if hit_trade and (run_trade_action is not None):
      curr_time = getattr(scratch, "curr_time", None)

      # ---------------------------------------------------------
      # [MOD] 去重：不要用 curr_time 做 sig（会导致每分钟都触发）
      # 尽量用稳定字段：动作描述 + 动作地点/事件（拿不到就退化）
      # ---------------------------------------------------------
      act_address = getattr(scratch, "act_address", None) or getattr(scratch, "curr_tile", None) or ""
      act_event = getattr(scratch, "act_event", None) or ""

      # 一个稳定签名：同一段“看盘/交易”动作不会因为时间跳动而重复触发
      sig = (act_desc_l, str(act_address), str(act_event))

      # ---------------------------------------------------------
      # [MOD] 按天清空 cache，避免无限增长
      # ---------------------------------------------------------
      day_key = ""
      if curr_time is not None:
        try:
          day_key = curr_time.date().isoformat()
        except Exception:
          day_key = str(curr_time)[:10]

      last_day = getattr(scratch, "_trade_trigger_cache_day", None)
      if last_day != day_key:
        scratch._trade_trigger_cache_day = day_key
        scratch._trade_trigger_cache = set()

      cache = getattr(scratch, "_trade_trigger_cache", None)
      if cache is None:
        cache = set()
        scratch._trade_trigger_cache = cache

      if sig not in cache:
        # 你可以把 symbol 放到 scratch 里（比如 scratch.trade_symbol），这里先给默认
        symbol = getattr(scratch, "trade_symbol", None) or "BTC/USDT"

        # dry_run 建议也放 scratch 配置，先默认 True
        dry_run = getattr(scratch, "trade_dry_run", True)

        res = run_trade_action(persona, symbol=symbol, now=curr_time, dry_run=dry_run)

        cache.add(sig)
        scratch._trade_action_last_sig = sig          # 保留：便于你 debug
        scratch._trade_action_last_result = res

  except Exception as e:
    print("WARNING: trade hook failed:", e)


  # =========================================================

  if "<random>" in plan and persona.scratch.planned_path == []: 
    persona.scratch.act_path_set = False

  # <act_path_set> is set to True if the path is set for the current action. 
  # It is False otherwise, and means we need to construct a new path. 
  if not persona.scratch.act_path_set: 
    # <target_tiles> is a list of tile coordinates where the persona may go 
    # to execute the current action. The goal is to pick one of them.
    target_tiles = None

    print ('aldhfoaf/????')
    print (plan)

    if "<persona>" in plan: 
      # Executing persona-persona interaction.
      target_p_tile = (personas[plan.split("<persona>")[-1].strip()]
                       .scratch.curr_tile)
      potential_path = path_finder(maze.collision_maze, 
                                   persona.scratch.curr_tile, 
                                   target_p_tile, 
                                   collision_block_id)
      if len(potential_path) <= 2: 
        target_tiles = [potential_path[0]]
      else: 
        potential_1 = path_finder(maze.collision_maze, 
                                persona.scratch.curr_tile, 
                                potential_path[int(len(potential_path)/2)], 
                                collision_block_id)
        potential_2 = path_finder(maze.collision_maze, 
                                persona.scratch.curr_tile, 
                                potential_path[int(len(potential_path)/2)+1], 
                                collision_block_id)
        if len(potential_1) <= len(potential_2): 
          target_tiles = [potential_path[int(len(potential_path)/2)]]
        else: 
          target_tiles = [potential_path[int(len(potential_path)/2+1)]]
    
    elif "<waiting>" in plan: 
      # Executing interaction where the persona has decided to wait before 
      # executing their action.
      x = int(plan.split()[1])
      y = int(plan.split()[2])
      target_tiles = [[x, y]]

    elif "<random>" in plan:
      plan = clean_plan_address(plan)
      if plan in maze.address_tiles:
        target_tiles = maze.address_tiles[plan]
        target_tiles = random.sample(list(target_tiles), 1)
      else:
          print("WARNING: unknown random address:", plan)
          return None, "", ""


    else: 
      # This is our default execution. We simply take the persona to the
      # location where the current action is taking place. 
      # Retrieve the target addresses. Again, plan is an action address in its
      # string form. <maze.address_tiles> takes this and returns candidate 
      # coordinates. 
      cleaned_plan = clean_plan_address(plan)

      if cleaned_plan in maze.address_tiles:
        target_tiles = maze.address_tiles[cleaned_plan]
      else:
        print("WARNING: unknown plan address:", plan, "=> cleaned as", cleaned_plan)
        return None, "", 

    # There are sometimes more than one tile returned from this (e.g., a tabe
    # may stretch many coordinates). So, we sample a few here. And from that 
    # random sample, we will take the closest ones. 
    if len(target_tiles) < 4: 
      target_tiles = random.sample(list(target_tiles), len(target_tiles))
    else:
      target_tiles = random.sample(list(target_tiles), 4)
    # If possible, we want personas to occupy different tiles when they are 
    # headed to the same location on the maze. It is ok if they end up on the 
    # same time, but we try to lower that probability. 
    # We take care of that overlap here.  
    persona_name_set = set(personas.keys())
    new_target_tiles = []
    for i in target_tiles: 
      curr_event_set = maze.access_tile(i)["events"]
      pass_curr_tile = False
      for j in curr_event_set: 
        if j[0] in persona_name_set: 
          pass_curr_tile = True
      if not pass_curr_tile: 
        new_target_tiles += [i]
    if len(new_target_tiles) == 0: 
      new_target_tiles = target_tiles
    target_tiles = new_target_tiles

    # Now that we've identified the target tile, we find the shortest path to
    # one of the target tiles. 
    curr_tile = persona.scratch.curr_tile
    collision_maze = maze.collision_maze
    closest_target_tile = None
    path = None
    for i in target_tiles: 
      # path_finder takes a collision_mze and the curr_tile coordinate as 
      # an input, and returns a list of coordinate tuples that becomes the
      # path. 
      # e.g., [(0, 1), (1, 1), (1, 2), (1, 3), (1, 4)...]
      curr_path = path_finder(maze.collision_maze, 
                              curr_tile, 
                              i, 
                              collision_block_id)
      if not closest_target_tile: 
        closest_target_tile = i
        path = curr_path
      elif len(curr_path) < len(path): 
        closest_target_tile = i
        path = curr_path

    # Actually setting the <planned_path> and <act_path_set>. We cut the 
    # first element in the planned_path because it includes the curr_tile. 
    persona.scratch.planned_path = path[1:]
    persona.scratch.act_path_set = True
  
  # Setting up the next immediate step. We stay at our curr_tile if there is
  # no <planned_path> left, but otherwise, we go to the next tile in the path.
  ret = persona.scratch.curr_tile
  if persona.scratch.planned_path: 
    ret = persona.scratch.planned_path[0]
    persona.scratch.planned_path = persona.scratch.planned_path[1:]

  description = f"{persona.scratch.act_description}"
  description += f" @ {persona.scratch.act_address}"

  execution = ret, persona.scratch.act_pronunciatio, description
  return execution















