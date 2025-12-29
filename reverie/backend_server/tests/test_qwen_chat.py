import openai

# 这里要确保从 utils.py 读到你配置的 api_key、api_base
from utils import openai_api_key, openai_api_base

openai.api_key = openai_api_key
openai.api_base = openai_api_base   # https://dashscope.aliyuncs.com/compatible-mode/v1

print("Testing Qwen ChatCompletion...")

resp = openai.ChatCompletion.create(
    model="qwen3-max",
    messages=[
        {"role": "user", "content": "你好，请简单介绍一下小镇仿真是什么？"}
    ]
)

print("Response:")
print(resp["choices"][0]["message"]["content"])



def run_gpt_prompt_act_obj_desc(act_game_object, act_desp, persona, verbose=False): 
  # 通用简易清洗：去掉首尾空格、结尾句号
  def _simple_clean(gpt_response, prompt=""):
      if not gpt_response:
          return ""
      cr = str(gpt_response).strip()
      if cr.endswith("."):
          cr = cr[:-1]
      return cr

  def __func_clean_up(gpt_response, prompt=""):
      return _simple_clean(gpt_response, prompt)

  def __func_validate(gpt_response, prompt=""):
      # 只要清洗以后不是空，就认为有效
      return bool(_simple_clean(gpt_response, prompt))

  def get_fail_safe(act_game_object):
      return f"{act_game_object} is idle"

  # ChatGPT Plugin ===========================================================
  def __chat_func_clean_up(gpt_response, prompt=""):
      return _simple_clean(gpt_response, prompt)

  def __chat_func_validate(gpt_response, prompt=""):
      return bool(_simple_clean(gpt_response, prompt))


  print ("asdhfapsh8p9hfaiafdsi;ldfj as DEBUG 6") ########
  gpt_param = {"model": "qwen3-max", "max_tokens": 15, 
               "temperature": 0, "top_p": 1, "stream": False,
               "frequency_penalty": 0, "presence_penalty": 0, "stop": None}
  prompt_template = "persona/prompt_template/v3_ChatGPT/generate_obj_event_v1.txt" ########
  prompt_input = create_prompt_input(act_game_object, act_desp, persona)  ########
  prompt = generate_prompt(prompt_input, prompt_template)
  example_output = "being fixed" ########
  special_instruction = "The output should ONLY contain the phrase that should go in <fill in>." ########
  fail_safe = get_fail_safe(act_game_object) ########
  output = ChatGPT_safe_generate_response(
      prompt,
      example_output,
      special_instruction,
      3,
      fail_safe,
      __chat_func_validate,
      __chat_func_clean_up,
      True
  )

  # ✅ 无论如何，output 都要被赋值成一个“非空字符串”
  if not output or output is False:
      output = fail_safe

  # ✅ 最后必须 return，一定不能让函数跑到底什么都不写
  return output, [output, prompt, gpt_param, prompt_input, fail_safe]
  # ChatGPT Plugin ===========================================================

  # ChatGPT Plugin ===========================================================



  # gpt_param = {"engine": "text-davinci-003", "max_tokens": 30, 
  #              "temperature": 0, "top_p": 1, "stream": False,
  #              "frequency_penalty": 0, "presence_penalty": 0, "stop": ["\n"]}
  # prompt_template = "persona/prompt_template/v2/generate_obj_event_v1.txt"
  # prompt_input = create_prompt_input(act_game_object, act_desp, persona)
  # prompt = generate_prompt(prompt_input, prompt_template)
  # fail_safe = get_fail_safe(act_game_object)
  # output = safe_generate_response(prompt, gpt_param, 5, fail_safe,
  #                                  __func_validate, __func_clean_up)

  # if debug or verbose: 
  #   print_run_prompts(prompt_template, persona, gpt_param, 
  #                     prompt_input, prompt, output)
  
  # return output, [output, prompt, gpt_param, prompt_input, fail_safe]