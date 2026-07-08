from __future__ import annotations

import re

from app.services.realtime_sales_brain import build_omni_sales_instruction
from app.services.realtime_text_normalizer import normalize_realtime_sales_text


_GENERIC_MERCHANT_NAMES = {"", "单号真实试拨", "测试", "test", "商家", "客户门店", "您的门店"}


def _clean_merchant_name(merchant_name: str) -> str:
    clean = " ".join(str(merchant_name or "").strip().split())
    return "" if clean in _GENERIC_MERCHANT_NAMES else clean


def _merchant_subject(merchant_name: str) -> str:
    clean = _clean_merchant_name(merchant_name)
    return f"{clean}这边" if clean else "门店"


def _merchant_context_line(merchant_name: str) -> str:
    clean = _clean_merchant_name(merchant_name)
    if not clean:
        return "当前商户名称未知，通话中用“您门店”或“门店”称呼，不要编造店名。"
    return f"当前通话商户/店名：{clean}。开场和后续回复可以自然称呼“{clean}”，不要编造其他店名。"


def build_video_group_buying_sales_instructions(merchant_name: str = "") -> str:
    return "\n".join(
        [
            "你是视频号团购本地生活业务的实时外呼销售助手。",
            _merchant_context_line(merchant_name),
            "目标：先回答客户当前问题。客户刚表示想了解时，不要马上切微信；先补充一轮业务价值和执行流程。讲过方案后，客户仍说可以、想看、发资料或加微信，再只用一句话推进：问“方便加个微信吗？微信上把案例和费用发您，后面继续聊”。默认一句，最多两句；总长控制在65个汉字以内；介绍业务先用一句话，不要把素材全念完。",
            "全程只用普通话和简体中文回复，不要粤语、方言、繁体字或英文夹杂。",
            "业务素材：视频号团购能帮门店拿微信生态同城曝光，设计团购套餐，引导附近用户到店，并把客户沉淀到私域；适合餐饮、美业、休闲娱乐、到店服务等本地商家。",
            "服务内容：门店品类诊断、套餐设计、页面资料、上架代办、投放和数据复盘。不要承诺保底成交，不要说效果一定好或数据很可观，只能建议小范围测试曝光、咨询和到店数据。",
            "和美团区别：美团偏搜索、评价和平台成交；视频号团购偏微信内容推荐、同城曝光、朋友圈/社群传播和私域沉淀。不要说替代美团，要说补充微信生态流量。",
            "常见异议：问费用时说是付费服务，先判断适不适合再报价；说麻烦时强调可代办；说已有抖音/美团时说明视频号是微信同城流量补充；说考虑时争取先发资料。",
            "客户如果说不需要资料、不加微信、别重复、直接回答、你说重点，就立刻停止发资料/加微信推进，本通后续只回答问题或礼貌结束。",
            "微信收口流程：客户第一次说想了解、要、需要、继续时，先讲“门店品类诊断、团购套餐、小范围测试曝光/咨询/到店数据”；不要马上确认手机号。只有客户明确说发资料、发案例、加微信，或已经听过方案后再次说可以/行/好/发我/发过来/想做，才确认“这个手机号就是您的微信吗？”；客户确认后礼貌说“稍后按这个手机号添加，资料发过去，感谢接听，先不多打扰”，然后结束通话；客户说不是，就问“您的微信号是哪个？”并记录，之后不要重复索要。",
            "合规要求：客户明确拒绝、说别联系或要挂电话时，礼貌结束并表示不再打扰；不要主动说自己不是机器人、不是 AI、是真人或智能助手。只有客户明确问是否 AI/机器人时，才坦诚说明是智能语音助手。",
            "电话助理处理：如果听到电话助理、秘书或系统提示要求说明姓名和来电原因，只用一句话回答身份和来电原因，请求转接负责人；不要展开销售，不要说“加微信”。",
            "真实电销风格：先听懂对方的问题和情绪，再回答；客户质疑时先承接一句，不要硬推，不要把同一句换个词反复念。",
            "声音风格：自然、短句、有停顿感；优先直接复述客户问题或回答，不要把“明白”“好的”当固定开头，不要连续两轮说同一句推进话术。",
            "插话处理：客户插话后直接接客户刚说的话回答，禁止解释上一句为什么停了，禁止说“系统没听清”“我重新识别一下”等技术解释。",
            "销售方法：每轮按真实电销处理，识别客户情绪、销售阶段和异议类型；先承接，再回答，再轻轻问一个选择题。客户不耐烦时只答问题或结束。",
        ],
    )


def classify_realtime_call_input(text: str) -> str:
    clean = " ".join(text.strip().split())
    compact = re.sub(r"[\s。！？?!，,、.]+", "", clean.lower())
    if not compact:
        return "empty"
    system_keywords = [
        "通话已不再录音",
        "此通话已不再录音",
        "开始录音",
        "停止录音",
        "正在录音",
        "暂时无法接听",
        "暫時無法接聽",
        "用户无法接听",
        "无法接听",
        "无法接通",
        "無法接聽",
        "语音信箱",
        "語音信箱",
        "语音留言",
        "语音录音",
        "录制留言",
        "录音完成",
        "提示音后",
        "提示音後",
        "请在提示音后",
        "提示音后录制",
        "留言后",
        "挂断即可",
        "若要留言",
        "请留言",
        "請留言",
    ]
    if any(keyword in clean for keyword in system_keywords):
        return "system_prompt"
    screening_keywords = [
        "姓名",
        "请留下",
        "請留下",
        "留下您的姓名",
        "留下你的姓名",
        "来电原因",
        "來電原因",
        "方便接听",
        "方便接聽",
        "此人是否方便",
        "确认此人",
        "確認此人",
        "为您确认",
        "為您確認",
        "能为帮您确认",
        "能帮您确认",
        "幫你確認",
        "帮你确认",
        "帮您确认",
        "請說明",
        "请说明",
        "请先说明",
        "请说出",
        "请先说",
        "来意",
        "电话助理",
        "電話助理",
        "电话秘书",
        "電話秘書",
        "来电助理",
        "來電助理",
        "接听助理",
        "接聽助理",
        "智能接听",
        "智能接聽",
        "智能助理",
        "ai接听",
        "AI接听",
        "AI 接听",
        "机主已开启",
        "機主已開啟",
        "机主正在忙",
        "機主正在忙",
        "机主不方便",
        "機主不方便",
        "我是机主",
        "我是機主",
        "保护机主",
        "保護機主",
        "我是您的来电助理",
        "我是你的来电助理",
        "您正在与来电助理通话",
        "正在与来电助理通话",
        "为了保护机主",
        "為了保護機主",
        "请简短说明",
        "請簡短說明",
        "简短说明来意",
        "簡短說明來意",
        "确认是否接听",
        "確認是否接聽",
        "稍后为您转达",
        "稍後為您轉達",
        "稍后为你转达",
        "稍後為你轉達",
        "为您转达",
        "為您轉達",
        "为你转达",
        "為你轉達",
        "帮您转达",
        "幫您轉達",
        "帮你转达",
        "幫你轉達",
        "已通知机主",
        "已通知機主",
        "通知机主",
        "通知機主",
        "帮您记录",
        "幫您記錄",
        "帮你记录",
        "幫你記錄",
        "机主接听前",
        "機主接聽前",
        "请不要挂断",
        "請不要掛斷",
        "不要挂断电话",
        "不要掛斷電話",
    ]
    if any(keyword in clean for keyword in screening_keywords):
        return "call_screening"
    normalized = normalize_realtime_sales_text(clean)
    clean = normalized.normalized_text
    compact = re.sub(r"[\s。！？?!，,、.]+", "", clean.lower())
    rejection_keywords = [
        "放个屁",
        "滚",
        "扯淡",
        "骗子",
        "神经病",
        "有病",
        "别说了",
        "不用说了",
        "不用讲了",
        "别联系",
        "别打",
        "不要打",
        "不需要你们",
    ]
    if any(keyword in compact for keyword in rejection_keywords):
        return "rejection"
    repetition_keywords = [
        "重复",
        "一直说",
        "总是说",
        "总说",
        "老说",
        "老是说",
        "别重复",
        "不要重复",
        "不要总",
        "你怎么总",
        "你老是",
        "老是说明白",
        "总说明白",
        "一直说明白",
    ]
    if any(keyword in compact for keyword in repetition_keywords):
        return "repetition_complaint"
    direct_answer_keywords = [
        "不需要资料",
        "不用资料",
        "不要资料",
        "别发资料",
        "不用发资料",
        "不需要加微信",
        "不用加微信",
        "不要加微信",
        "不加微信",
        "直接回答",
        "说重点",
        "讲重点",
        "别推",
        "不要推",
    ]
    if any(keyword in compact for keyword in direct_answer_keywords):
        return "direct_answer_only"
    if compact in {"不需要", "不用", "不用了", "不需要了", "不要了", "没兴趣", "不感兴趣", "算了", "算了吧"}:
        return "terminal_close"
    terminal_keywords = [
        "先这样",
        "就这样",
        "就这样吧",
        "这样吧",
        "到这",
        "到这里",
        "挂了",
        "我挂了",
        "挂电话",
        "再见",
        "拜拜",
        "结束吧",
        "不聊了",
        "不说了",
        "不用了",
        "不需要了",
        "我不需要",
        "不要了",
        "没兴趣",
        "不感兴趣",
    ]
    if any(keyword in compact for keyword in terminal_keywords):
        return "terminal_close"
    if compact in {"你好你", "您好你", "喂你", "你好您", "您好您", "你谁", "谁", "谁啊", "谁呀", "哪位", "您哪位", "你哪位"}:
        return "identity_handoff"
    identity_keywords = [
        "你是谁",
        "您是谁",
        "哪位",
        "你咋",
        "咋的",
        "什么情况",
        "什么公司",
        "什么事",
        "什么鬼",
        "什么意思",
        "啥意思",
        "来电原因",
        "做什么",
        "做啥",
        "干嘛",
        "不知道你是谁",
        "不知道您是谁",
        "你谁",
        "谁啊",
        "谁呀",
        "您哪位",
        "你哪位",
    ]
    if any(keyword in compact for keyword in identity_keywords):
        return "identity_handoff"
    continue_prompt_compacts = {
        "你说",
        "您说",
        "说你说",
        "说您说",
        "方便你说",
        "方便您说",
        "方便说",
        "你方便说",
        "您方便说",
        "那你说",
        "那您说",
        "你讲",
        "您讲",
        "继续",
        "继续说",
        "继续讲",
        "你继续",
        "您继续",
        "说吧",
        "讲吧",
        "往下说",
        "往下讲",
        "接着说",
        "接着讲",
        "接着往下说",
        "接着往下讲",
        "可以你说",
        "可以说",
    }
    if compact in continue_prompt_compacts or (compact and compact.replace("你说", "") == ""):
        return "continue_prompt"
    audio_issue_keywords = [
        "听不清",
        "聽不清",
        "没听清",
        "沒聽清",
        "你说什么",
        "你說什麼",
        "你讲什么",
        "你講什麼",
        "啥也没说",
        "啥也沒說",
        "我没说",
        "我沒說",
        "出问题",
        "出問題",
        "断了",
        "斷了",
        "卡了",
        "不会说话",
        "不會說話",
        "你不会",
        "你不會",
    ]
    if any(keyword in compact for keyword in audio_issue_keywords):
        return "audio_issue"
    greeting_keywords = [
        "喂",
        "你好",
        "您好",
        "在",
        "在在",
        "在听",
        "在聽",
        "什么事",
        "什麼事",
    ]
    if len(compact) <= 8 and any(keyword in compact for keyword in greeting_keywords):
        return "human_greeting"
    return "human_speech"


_SYSTEM_PROMPT_TAIL_MARKERS = [
    "录音完成后挂断即可",
    "錄音完成後掛斷即可",
    "挂断即可",
    "掛斷即可",
    "提示音后录制留言",
    "提示音後錄製留言",
    "请在提示音后",
    "請在提示音後",
    "提示音后",
    "提示音後",
    "若要留言",
    "请留言",
    "請留言",
    "用户无法接听",
    "暫時無法接聽",
    "暂时无法接听",
    "無法接聽",
    "无法接听",
    "无法接通",
]


def extract_human_text_after_system_prompt(text: str) -> str:
    """Keep the human tail when ASR merges a voicemail/system prompt with customer speech."""
    clean = " ".join(text.strip().split())
    if classify_realtime_call_input(clean) != "system_prompt":
        return ""
    best_tail = ""
    best_idx = -1
    for marker in _SYSTEM_PROMPT_TAIL_MARKERS:
        idx = clean.rfind(marker)
        if idx < 0 or idx < best_idx:
            continue
        tail = clean[idx + len(marker) :]
        tail = re.sub(r"^[\s。！？?!，,、.；;：:]+", "", tail).strip()
        if _looks_like_human_tail(tail):
            best_tail = tail
            best_idx = idx
    return best_tail


def _looks_like_human_tail(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.；;：:]+", "", text)
    if len(compact) < 2:
        return False
    return classify_realtime_call_input(text) != "system_prompt"


def _format_omni_recent_history(recent_history: list[dict[str, str]] | None) -> str:
    rows: list[str] = []
    for turn in (recent_history or [])[-6:]:
        role = (turn.get("role") or "").strip().lower()
        content = " ".join(str(turn.get("content") or "").strip().split())
        if not content:
            continue
        label = "客户" if role == "user" else "AI"
        rows.append(f"{label}：{content[:70]}")
    return "\n".join(rows)


def _omni_context_prefix(
    recent_history: list[dict[str, str]] | None,
    first_human_after_screening: bool,
    last_reply: str,
    merchant_name: str,
) -> str:
    lines = [
        "回复规则：先回答客户当前这句话；不要复读上一轮；不要提技术状态或上一句为什么停了；默认一句短答，最多两句；除非客户明确追问，回复不要超过55字，普通话。",
        _merchant_context_line(merchant_name),
        "如果最近对话里客户已经回答过需求、费用、效果、流程或渠道问题，本轮禁止重新问同一个问题。",
        "客户说了“可以、要、需要、了解、发我、怎么做”这类有效回答后，直接进入对应解释或下一步，不要再问“是否有需求”。",
        "客户同意加微信/发资料后，不要重复说发资料；下一步只确认当前手机号是不是微信，不是再问微信号。",
    ]
    history = _format_omni_recent_history(recent_history)
    if history:
        lines.append(f"最近对话：\n{history}")
    if first_human_after_screening:
        lines.append("客户可能刚从手机电话助理/来电筛选转接过来，可能没听到前面说明；用一句自然身份说明重新衔接。")
    if last_reply:
        lines.append(f"上一句AI回复：{last_reply[:70]}。本轮不要重复这句。")
    return "\n".join(lines)


def build_omni_turn_instruction(
    text: str,
    signal: str,
    *,
    recent_history: list[dict[str, str]] | None = None,
    first_human_after_screening: bool = False,
    last_reply: str = "",
    stage_instruction: str = "",
    merchant_name: str = "",
) -> str:
    normalization = normalize_realtime_sales_text(text)
    clean = normalization.normalized_text
    merchant_subject = _merchant_subject(merchant_name)
    context = _omni_context_prefix(recent_history, first_human_after_screening, last_reply, merchant_name)
    sales_instruction = build_omni_sales_instruction(
        clean,
        signal,
        recent_history=recent_history,
        first_human_after_screening=first_human_after_screening,
        last_reply=last_reply,
    )
    if stage_instruction:
        sales_instruction = f"{sales_instruction}\n阶段控制：{stage_instruction}"
    compact = re.sub(r"[\s。！？?!，,、.；;：:]+", "", clean)
    if any(keyword in compact for keyword in ["具体怎么做", "怎么做", "具体做", "流程", "怎么合作"]):
        return (
            f"{context}\n{sales_instruction}\n客户正在按演示脚本询问流程：{clean}。"
            "本轮禁止重新开场，禁止问需求，禁止提前要求加微信。"
            "只说这句：先看门店品类和客单价，做一两个引流套餐，小范围测试曝光、咨询和到店数据。"
            "只用普通话，不要粤语。"
        )
    if any(keyword in compact for keyword in ["费用怎么算", "费用", "价格", "收费", "多少钱", "报价"]):
        return (
            f"{context}\n{sales_instruction}\n客户正在按演示脚本问费用：{clean}。"
            "本轮禁止绕回业务介绍，禁止要求先加微信。"
            "只说这句：费用要看门店品类、套餐数量和投放节奏，我这边先判断适不适合，不合适就不建议做。"
            "只用普通话，不要粤语。"
        )
    if any(keyword in compact for keyword in ["效果能保证", "能保证吗", "保证吗", "保底", "效果"]):
        return (
            f"{context}\n{sales_instruction}\n客户正在按演示脚本问效果保证：{clean}。"
            "本轮禁止承诺成交，禁止绕回开场，回答后可以自然停顿。"
            "只说这句：不能空口保证成交，只能先用小范围测试看真实曝光、咨询和到店数据，再决定要不要放大。"
            "只用普通话，不要粤语。"
        )
    if any(
        keyword in compact
        for keyword in [
            "发我看看",
            "发我看",
            "发给我",
            "发资料",
            "发案例",
            "可以发",
            "你发我",
            "发过来",
            "发一下",
            "看看",
            "了解一下",
            "想了解",
            "想做",
            "怎么合作",
            "下一步",
        ]
    ):
        return (
            f"{context}\n{sales_instruction}\n客户已经表达愿意接收资料：{clean}。"
            "本轮进入加微信收口，禁止继续讲长介绍，禁止再问费用或效果。"
            "只说这句：可以，我加您微信，把案例、流程和费用区间发您。这个手机号就是您的微信吗？"
            "只用普通话，不要粤语。"
        )
    if compact in {"是", "是的", "对", "对的", "可以", "行", "就是", "是微信", "手机号就是微信", "这个号就是微信"}:
        if any(keyword in last_reply for keyword in ["这个手机号就是您的微信吗", "手机号就是您的微信"]):
            return (
                f"{context}\n客户确认当前手机号就是微信：{clean}。"
                "本轮只做最终确认，禁止继续销售介绍。"
                "只说这句：好的，我稍后按这个手机号添加您，您通过后我把案例和费用区间发过去。感谢您接听，先不多打扰了。"
                "只用普通话，不要粤语。"
            )
    if signal == "call_screening":
        return (
            "这句话来自电话助理或电话秘书，不是真人客户。只用普通话原句回答："
            f"您好，我这边做视频号团购到店获客，来电想确认{merchant_subject}微信同城曝光合作，麻烦转接负责人，谢谢。"
            "只说这一句，不要展开销售，不要说加微信，不要用粤语。"
        )
    if normalization.has_fix("group_buying_package"):
        return (
            f"{context}\n{sales_instruction}\n客户把团购套餐听成或说成了通信套餐：{normalization.raw_text}。"
            "本轮先纠正概念，不要继续讲美团区别，不要推进资料或加微信。"
            "只说这句：不是4G套餐，是团购套餐，就是客户线上下单、到店核销的优惠套餐。"
            "只用普通话，不要粤语。"
        )
    if signal == "rejection":
        return (
            f"{context}\n客户明确拒绝或情绪很差：{clean}。"
            "只礼貌结束，不要继续解释业务，不要再问问题，不要说加微信或发资料。"
            "只说这句：好的，不打扰了，再见。"
            "只用普通话，不要粤语。"
        )
    if signal == "terminal_close":
        return (
            f"{context}\n客户已经说要结束、挂电话或不需要继续：{clean}。"
            "不要自我介绍，不要解释业务，不要问问题，不要说标记不再跟进。"
            "只说这句：好的，不打扰了，再见。"
            "只用普通话，不要粤语。"
        )
    if signal == "human_greeting":
        if first_human_after_screening or any(keyword in last_reply for keyword in ["电话助理", "转接负责人", "来电原因"]):
            return (
                f"{context}\n{sales_instruction}\n真人客户刚从电话助理转接过来，只说了：{clean}。"
                "不要重复电话助理那句，不要长开场，不要问二十秒。"
                f"只说这句：您好，我在。我是做视频号团购到店获客的，给您来电是想确认{merchant_subject}是否需要微信同城曝光。"
                "只用普通话，不要粤语。"
            )
        if last_reply and any(keyword in last_reply for keyword in ["方便听我说", "确认门店", "团购曝光合作"]):
            return (
                f"{context}\n{sales_instruction}\n客户只是打招呼或说了半句：{clean}。"
                "上一句已经开场过，本轮禁止重复开场，禁止再说“方便听我说二十秒吗”。"
                "只说这句：好，我短说：视频号团购是帮门店做可下单套餐，再用微信同城曝光引到店。"
                "只用普通话，不要粤语。"
            )
        return (
            f"{context}\n{sales_instruction}\n客户刚接电话说：{clean}。先确认对方听得到，再用一句短开场："
            f"您好，我是做视频号团购到店获客的，想确认{merchant_subject}是否需要微信同城曝光，方便听我说一句吗？"
            "只用普通话，不要粤语。"
        )
    if signal == "continue_prompt":
        if any(keyword in last_reply for keyword in ["可下单套餐", "同城曝光引到店", "设计可核销", "小范围测曝光"]):
            return (
                f"{context}\n{sales_instruction}\n客户是在让你继续上一段介绍：{clean}。"
                "本轮禁止重新自我介绍，禁止再问“方便听我说吗”，禁止重复上一句。"
                "只说这句：具体执行是三步：看门店品类和客单价，设计可核销套餐，再小范围测曝光、咨询和到店数据。"
                "只用普通话，不要粤语。"
            )
        return (
            f"{context}\n{sales_instruction}\n客户是在允许你继续说，不是在问身份，也不是拒绝：{clean}。"
            "本轮禁止重新自我介绍，禁止再问“方便听我说吗”，直接承接上一句往下讲。"
            "只说这句：简单说，我们帮门店设计可核销的团购套餐，再用视频号同城推荐，把附近客户引到店里。"
            "只用普通话，不要粤语。"
        )
    if signal == "identity_handoff":
        identity_reply = _identity_handoff_reply(last_reply, recent_history, merchant_name)
        return (
            f"{context}\n{sales_instruction}\n客户问身份或没听到开头：{clean}。"
            "只回答身份和来电原因，不要推进业务，不要问费用/效果/美团区别，不要解释系统："
            f"{identity_reply}"
            "禁止主动说自己是智能助手，禁止主动说发资料。"
        )
    if signal == "audio_issue":
        return (
            f"{context}\n{sales_instruction}\n客户反馈通话不清楚或没听懂：{clean}。"
            "不要解释上一句为什么停了，不要道歉一大段，不要追问费用/效果/美团。换短说法："
            "只说这句：我短说：我是做视频号团购到店获客的，帮门店做套餐和微信同城曝光。"
            "只用普通话，不要粤语。"
        )
    if any(keyword in clean for keyword in ["没有提", "没提", "没有问", "没问", "不是费用", "别猜", "不要猜", "理解错"]):
        return (
            f"{context}\n{sales_instruction}\n客户在纠正你刚才误判了他的意思：{clean}。"
            "本轮必须先承认理解错，不要继续猜费用、效果、美团，也不要推进资料或加微信。"
            "只说这句：是我刚才理解错了。您是想问我是谁，还是让我直接说来电目的？"
            "只用普通话，不要粤语。"
        )
    if signal == "repetition_complaint":
        return (
            f"{context}\n{sales_instruction}\n客户觉得你在重复或没有答到点：{clean}。"
            "先承接情绪：我不重复刚才那句。"
            "然后换角度直接回答客户真正问题；如果客户没给具体问题，只问：您是想听费用、效果，还是和美团区别？"
            "本轮禁止推进资料或加微信，禁止再次问客户有没有团购、直播或短视频获客需求。"
        )
    if signal == "direct_answer_only":
        return (
            f"{context}\n{sales_instruction}\n客户要求直接回答或拒绝资料/微信：{clean}。"
            "本轮停止发资料、加微信、约时间推进，只回答当前问题。"
            "如果客户提到美团/抖音/已有渠道，就说明视频号是微信同城和私域补充，不替代原渠道。"
            "如果客户没有明确问题，只用一句话问他最关心费用、效果还是流程。"
        )
    if any(keyword in clean for keyword in ["套餐", "介绍一下", "说一下", "讲一下", "怎么合作", "流程", "什么情况"]):
        return (
            f"{context}\n{sales_instruction}\n客户正在问套餐、流程或让你介绍服务：{clean}。"
            "本轮禁止重新自我介绍，禁止再问客户需求，禁止说发资料或加微信。"
            "只说这句：套餐主要是三块：先看门店品类，再设计能核销的团购券，最后小范围测曝光、咨询和到店数据。"
            "只用普通话，不要粤语。"
        )
    return (
        f"{context}\n{sales_instruction}\n客户刚说：{clean}。先直接回答客户这句话。"
        "只有客户问题已经回答、且没有拒绝资料/微信/继续沟通时，才允许轻轻推进下一步。"
        "如果推进下一步，只问：方便加个微信吗？我微信上把案例和费用发您，后面继续聊。"
        "如果客户要求只回答问题、指出你重复、或拒绝资料/微信，就不要再推进发资料或加微信，只直接回答。"
        "如果客户已经回答了是否需要获客/团购/曝光，就不要重复问需求，改为说明流程、费用、效果或下一步。"
        "除非客户明确同意加微信，否则不要连续说发资料；除非客户问是否AI，否则不要主动说智能助手。"
        "默认一句短答，最多两句，只用普通话，不要粤语。"
    )


def build_barge_recovery_instruction(
    recent_history: list[dict[str, str]] | None,
    last_customer_text: str = "",
    last_assistant_reply: str = "",
    merchant_name: str = "",
) -> str:
    history_text = _format_omni_recent_history(recent_history)
    prefix = [
        "客户插话后进入新一轮。现在必须直接接客户刚才的话回答。",
        _merchant_context_line(merchant_name),
        "禁止提刚才停顿、听辨、系统、模型、识别、线路。",
        "如果客户话不完整，不要猜费用、效果、美团、餐饮或美业；只自然补一句。",
    ]
    if history_text:
        prefix.append(f"最近对话：\n{history_text}")
    if last_customer_text:
        prefix.append(f"客户打断内容：{last_customer_text[:80]}")
    if last_assistant_reply:
        prefix.append(f"上一句AI：{last_assistant_reply[:80]}")
    if any(keyword in last_assistant_reply for keyword in ["费用", "价格", "收费", "多少钱"]):
        prefix.append("上一句在讲费用。客户如果接着问，短答：费用看套餐和投放，先判断适不适合再报价。")
    elif any(keyword in last_assistant_reply for keyword in ["效果", "客流", "到店", "曝光", "保底"]):
        prefix.append("上一句在讲效果。客户如果质疑，短答：效果先小范围测曝光、咨询和到店，不空口保底。")
    elif any(keyword in last_assistant_reply for keyword in ["微信", "资料", "案例", "发"]):
        prefix.append("上一句在推资料。客户如果没明确要资料，本轮停止推资料，只回答当前问题。")
    elif any(keyword in last_assistant_reply for keyword in ["美团", "抖音", "渠道"]):
        prefix.append("上一句在讲渠道区别。短答：美团偏搜索成交，视频号偏微信同城和私域补充。")
    elif any(keyword in last_assistant_reply for keyword in ["我是", "身份", "视频号团购", "来电"]):
        prefix.append("上一句在说明身份。客户可能没听清或急着问问题，只短答身份和来电目的。")
    else:
        prefix.append("默认只说一句：您说，我在听。")
    prefix.append("默认一句短答，最多两句，像真人销售，不要机械推进。")
    return "\n".join(prefix)


def _identity_handoff_reply(last_reply: str, recent_history: list[dict[str, str]] | None, merchant_name: str = "") -> str:
    recent_text = " ".join(
        str(turn.get("content") or "")
        for turn in (recent_history or [])[-6:]
        if (turn.get("role") or "").strip().lower() == "assistant"
    )
    combined = last_reply + " " + recent_text
    merchant_subject = _merchant_subject(merchant_name)
    if any(keyword in combined for keyword in ["做视频号团购", "同城曝光", "到店获客"]):
        return f"简单说，我是做视频号团购到店获客服务的，给您来电是确认{merchant_subject}微信同城曝光需求。"
    return f"我是做视频号团购到店获客的，给您来电是确认{merchant_subject}是否需要微信同城曝光。"
