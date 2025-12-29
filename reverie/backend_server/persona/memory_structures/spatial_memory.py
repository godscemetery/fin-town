"""
Author: Joon Sung Park (joonspk@stanford.edu)

File: spatial_memory.py
Description: Defines the MemoryTree class that serves as the agents' spatial
memory that aids in grounding their behavior in the game world. 
"""
import json
import sys
sys.path.append('../../')

from utils import *
from global_methods import *

class MemoryTree: 
  def __init__(self, f_saved): 
    self.tree = {}
    if check_if_file_exists(f_saved): 
      self.tree = json.load(open(f_saved))


  def print_tree(self): 
    def _print_tree(tree, depth):
      dash = " >" * depth
      if type(tree) == type(list()): 
        if tree:
          print (dash, tree)
        return 

      for key, val in tree.items(): 
        if key: 
          print (dash, key)
        _print_tree(val, depth+1)
    
    _print_tree(self.tree, 0)
    

  def save(self, out_json):
    with open(out_json, "w") as outfile:
      json.dump(self.tree, outfile) 



  def get_str_accessible_sectors(self, curr_world): 
    """
    Returns a summary string of all the arenas that the persona can access 
    within the current sector. 

    Note that there are places a given persona cannot enter. This information
    is provided in the persona sheet. We account for this in this function. 

    INPUT
      None
    OUTPUT 
      A summary string of all the arenas that the persona can access. 
    EXAMPLE STR OUTPUT
      "bedroom, kitchen, dining room, office, bathroom"
    """
    x = ", ".join(list(self.tree[curr_world].keys()))
    return x


  def get_str_accessible_sector_arenas(self, sector): 
    """
    Returns a summary string of all the arenas that the persona can access 
    within the current sector. 

    Note that there are places a given persona cannot enter. This information
    is provided in the persona sheet. We account for this in this function. 

    INPUT
      None
    OUTPUT 
      A summary string of all the arenas that the persona can access. 
    EXAMPLE STR OUTPUT
      "bedroom, kitchen, dining room, office, bathroom"
    """
    curr_world, curr_sector = sector.split(":")
    if not curr_sector: 
      return ""
    x = ", ".join(list(self.tree[curr_world][curr_sector].keys()))
    return x


  def get_str_accessible_arena_game_objects(self, arena):
    """
    输入保持与原版一致：arena 是 "world:sector:arena" 的字符串
    增强：
    - 允许多段（取前三段）
    - 去掉 {}
    - 大小写兜底
    - 在失败时打印 tree 结构用于定位 <random> 根因
    """
    debug = False
    # ---------- 1. 基本合法性 ----------
    if not isinstance(arena, str):
        if debug:
            print("[TREE DEBUG] arena is not str:", repr(arena))
        return ""

    parts = arena.split(":")
    if len(parts) < 3:
        if debug:
            print("[TREE DEBUG] arena split < 3:", repr(arena))
        return ""

    curr_world, curr_sector, curr_arena = parts[0], parts[1], parts[2]

    if not curr_arena:
        if debug:
            print("[TREE DEBUG] empty curr_arena:", repr(arena))
        return ""

    # ---------- 2. arena 名称清洗 ----------
    raw_arena = str(curr_arena).strip()
    cleaned_arena = raw_arena.strip("{}").strip()

    candidates = [
        raw_arena,
        raw_arena.lower(),
        cleaned_arena,
        cleaned_arena.lower(),
    ]

    # ---------- 3. world / sector 查找 ----------
    if curr_world not in self.tree:
        if debug:
            print("[TREE DEBUG] world not found:", repr(curr_world))
            print("[TREE DEBUG] available worlds:", list(self.tree.keys())[:10])
            print("[TREE DEBUG] original arena:", repr(arena))
        return ""

    if curr_sector not in self.tree[curr_world]:
        if debug:
            print("[TREE DEBUG] sector not found:", repr(curr_sector))
            print("[TREE DEBUG] available sectors:",
                  list(self.tree[curr_world].keys())[:10])
            print("[TREE DEBUG] original arena:", repr(arena))
        return ""

    sector_dict = self.tree[curr_world][curr_sector]
    if not sector_dict:
        if debug:
            print("[TREE DEBUG] sector exists but empty:", repr(curr_sector))
        return ""

    # ---------- 4. arena key 匹配 ----------
    for key in candidates:
        if key in sector_dict:
            try:
                return ", ".join(list(sector_dict[key]))
            except Exception as e:
                if debug:
                    print("[TREE DEBUG] error reading objects for key:", repr(key))
                    print("[TREE DEBUG] exception:", e)
                return ""

    # ---------- 5. 走到这里 = 真正导致 <random> 的地方 ----------
    if debug:
        print("[TREE DEBUG] arena not found in sector")
        print("  world  =", repr(curr_world))
        print("  sector =", repr(curr_sector))
        print("  arena(raw)    =", repr(raw_arena))
        print("  arena(clean) =", repr(cleaned_arena))
        print("  tried keys   =", candidates)
        print("  available arenas =", list(sector_dict.keys()))
        print("  original arena string =", repr(arena))

    return ""







if __name__ == '__main__':
  x = f"../../../../environment/frontend_server/storage/the_ville_base_LinFamily/personas/Eddy Lin/bootstrap_memory/spatial_memory.json"
  x = MemoryTree(x)
  x.print_tree()

  print (x.get_str_accessible_sector_arenas("dolores double studio:double studio"))







