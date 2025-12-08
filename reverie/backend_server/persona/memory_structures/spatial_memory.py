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


  def get_str_accessible_arena_game_objects(self, act_address):
    """
    根据当前 world / sector / arena，返回这个区域可交互的物体。
    为了适配大模型输出，自动清理 { } 和大小写等问题，
    并且允许 act_address 是 (world, sector, arena, ...) 这种长度>3 的元组。
    """

    # ---- 1. 安全地解析 act_address ----
    # 允许 act_address 是 tuple/list，长度>=3，多余的直接丢掉
    if isinstance(act_address, (list, tuple)):
        if len(act_address) >= 3:
            curr_world, curr_sector, curr_arena = act_address[0], act_address[1], act_address[2]
        else:
            # 不够 3 个元素，信息不全，直接返回空字符串避免崩溃
            return ""
    else:
        # 不是序列（比如 None 或字符串），也直接放弃
        return ""

    # ---- 2. 统一清洗 arena 名字：去掉大括号、前后空格，转小写 ----
    raw_arena = str(curr_arena).strip()
    cleaned_arena = raw_arena.strip("{}").strip()
    cleaned_arena_lower = cleaned_arena.lower()

    # 取出对应 sector 下的字典
    sector_dict = self.tree.get(curr_world, {}).get(curr_sector, {})

    # 依次尝试几种可能的 key 形式
    for key in (
        raw_arena,
        raw_arena.lower(),
        cleaned_arena,
        cleaned_arena_lower,
    ):
        if key in sector_dict:
            return ", ".join(list(sector_dict[key]))

    # 实在找不到，就返回空字符串，不让仿真直接崩
    return ""



if __name__ == '__main__':
  x = f"../../../../environment/frontend_server/storage/the_ville_base_LinFamily/personas/Eddy Lin/bootstrap_memory/spatial_memory.json"
  x = MemoryTree(x)
  x.print_tree()

  print (x.get_str_accessible_sector_arenas("dolores double studio:double studio"))







