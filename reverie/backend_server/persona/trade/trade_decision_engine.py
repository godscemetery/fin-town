# -*- coding: utf-8 -*-
"""
Trade Decision Engine
---------------------
整合：
- 市场 & 账户 context
- Agent 记忆 digest
- LLM（Qwen3）决策
- JSON 解析 + 风控
"""

from __future__ import annotations
from typing import Dict, Any
import os
from trade_context import format_context_text
from trade_memory_digest import get_trade_memory_digest
from trade_contract import parse_trade_decision, validate_and_guard
from global_methods import *
from persona.prompt_template.gpt_structure import *
from persona.prompt_template.print_prompt import *

from persona.prompt_template.gpt_structure import GPT_request  # 视你工程实际路径


# =========================
# 主入口
# =========================

def run_gpt_prompt_trade_decision(
    *,
    persona,
    symbol: str,
    trade_context: dict,
    now_time,
    verbose: bool = False,
):
    """
    交易决策 LLM 调用（稳健版）：
    - 优先：GPT_request(prompt, gpt_param) 直连拿结果（你已验证可返回 JSON）
    - 兜底：ChatGPT_safe_generate_response（可能内部黑盒/返回 False）
    返回：(model_output_str, debug_info)
    """
    import os
    from trade_context import format_context_text
    from trade_memory_digest import get_trade_memory_digest
    from trade_contract import extract_json_from_text

    # 这里按你工程实际 import（你之前已能 import 成功）
    from persona.prompt_template.gpt_structure import generate_prompt, GPT_request, ChatGPT_safe_generate_response

    # =========================
    # 1) prompt_input
    # =========================
    context_text = format_context_text(trade_context)
    memory_text = get_trade_memory_digest(
        persona,
        symbol=symbol,
        now_time=now_time,
    )
    prompt_input = [context_text, memory_text]

    # =========================
    # 2) prompt_template 路径
    # =========================
    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))            # .../persona/trade
    _BACKEND_SERVER_DIR = os.path.dirname(os.path.dirname(_THIS_DIR)) # .../backend_server

    prompt_template = os.path.join(
        _BACKEND_SERVER_DIR,
        "persona",
        "prompt_template",
        "v3_ChatGPT",
        "trade_decision_v1.txt",
    )

    # ✅ 关键：最终 prompt 必须落到变量 prompt
    prompt = generate_prompt(prompt_input, prompt_template)

    # =========================
    # 3) LLM 参数（直连用这个）
    # =========================
    gpt_param = {
        "model": "qwen3-max",
        "max_tokens": 512,   # 防止截断
        "temperature": 0,
        "top_p": 1,
        "stream": False,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stop": None,
    }

    # =========================
    # 4) fail-safe（必须纯 JSON）
    # =========================
    def get_fail_safe(reason="LLM failure", note="模型失败，采取观望"):
        return (
            '{"decision":"hold","symbol":"%s","size_percent":10,'
            '"reason":["%s"],'
            '"memory_note":"%s"}'
            % (symbol, reason, note)
        )

    # =========================
    # 5) clean/validate（给 safe_generate 用）
    # =========================
    def __func_clean_up(gpt_response, prompt_str=""):
        if gpt_response is None:
            return ""
        if not isinstance(gpt_response, str):
            gpt_response = str(gpt_response)
        return gpt_response.strip()

    def __func_validate(gpt_response, prompt_str=""):
        try:
            if gpt_response is None:
                return False
            if not isinstance(gpt_response, str):
                gpt_response = str(gpt_response)
            _ = extract_json_from_text(gpt_response)
            return True
        except Exception:
            return False

    # =========================
    # 6) 辅助：尝试从输出中抽 JSON（用于直连/兜底统一判断）
    # =========================
    def _try_extract_json_text(text: str) -> str | None:
        if text is None:
            return None
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        try:
            j = extract_json_from_text(text)  # 返回 dict
            # 保留原始输出（因为 parse_trade_decision 可能要看原字符串）
            # 但这里我们至少确认“能抽到 JSON”
            return text
        except Exception:
            return None

    # =========================
    # 7) 优先：GPT_request 直连（只要能抽到 JSON 就直接用）
    # =========================
    used_path = None
    raw_output = None
    raw_valid_text = None
    raw_exc = None

    try:
        raw_output = GPT_request(prompt, gpt_param)
        if verbose:
            print("[DEBUG] GPT_request raw type:", type(raw_output), "head:", str(raw_output)[:300])
        raw_valid_text = _try_extract_json_text(raw_output)
        if raw_valid_text is not None:
            used_path = "GPT_request"
            # ✅ 直接返回模型输出（而不是走 safe_generate）
            return raw_valid_text, [
                raw_valid_text,
                "used_path=" + used_path,
                prompt_template,
                prompt_input,
                gpt_param,
                get_fail_safe(),
                prompt[:400],
            ]
    except Exception as e:
        raw_exc = repr(e)
        if verbose:
            print("[DEBUG] GPT_request exception:", raw_exc)

    # =========================
    # 8) 兜底：safe_generate（如果直连失败/抽不到 JSON）
    # =========================
    example_output = (
        '{"decision":"hold","symbol":"BTC/USDT","size_percent":10,'
        '"reason":["No clear signal"],'
        '"memory_note":"等待更明确趋势"}'
    )
    special_instruction = (
        "Output ONLY ONE valid JSON object. "
        "No explanation, no markdown, no extra text."
    )

    try:
        output = ChatGPT_safe_generate_response(
            prompt,
            example_output,
            special_instruction,
            3,
            get_fail_safe(),
            __func_validate,
            __func_clean_up,
            verbose,
            gpt_param=gpt_param,  # 如果不支持会 TypeError
        )
    except TypeError:
        output = ChatGPT_safe_generate_response(
            prompt,
            example_output,
            special_instruction,
            3,
            get_fail_safe(),
            __func_validate,
            __func_clean_up,
            verbose,
        )
    except Exception as e:
        output = None
        if verbose:
            print("[DEBUG] safe_generate exception:", repr(e))

    # safe_generate 也可能返回 bool False
    if not isinstance(output, str):
        output = ""

    safe_valid_text = _try_extract_json_text(output)
    if safe_valid_text is not None:
        used_path = "safe_generate"
        return safe_valid_text, [
            safe_valid_text,
            "used_path=" + used_path,
            prompt_template,
            prompt_input,
            gpt_param,
            get_fail_safe(),
            prompt[:400],
            "raw_exc=" + str(raw_exc),
            "raw_head=" + (str(raw_output)[:200] if raw_output is not None else "None"),
        ]

    # =========================
    # 9) 最终兜底：返回 fail-safe JSON（保证 parse 永远能过）
    # =========================
    used_path = "fail_safe"
    final_fallback = get_fail_safe(
        reason="LLM failure (no valid JSON)",
        note="模型输出无法解析为JSON→观望",
    )
    return final_fallback, [
        final_fallback,
        "used_path=" + used_path,
        prompt_template,
        prompt_input,
        gpt_param,
        get_fail_safe(),
        prompt[:400],
        "raw_exc=" + str(raw_exc),
        "raw_head=" + (str(raw_output)[:200] if raw_output is not None else "None"),
        "safe_head=" + (str(output)[:200] if output is not None else "None"),
    ]



