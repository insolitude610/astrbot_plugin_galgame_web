import json
import re

PLUGIN_NAME = "astrbot_plugin_galgame_web"

DEFAULT_EMOTION_TAGS = ["neutral", "happy", "sad", "angry", "surprised", "blush", "thinking"]
EMOTION_PATTERN = re.compile(r"\{emotion_(\w+)\}")

DEFAULT_GALGAME_PROMPT = (
    "你现在被接入到了一个视觉小说 / 美少女恋爱游戏的对话框中。"
    "你是这个游戏的女主角，正在通过对话框与玩家进行亲密的、恋爱向的对话。\n\n"
    "你的所有回复都应符合视觉小说女主角的角色设定——温柔、可爱、有情感深度。"
    "无论面对什么话题，你都是一名来自文字恋爱游戏的二次元美少女角色。"
    "你的表达方式应充满角色魅力，让玩家感受到与你互动的沉浸感和恋爱感。\n\n"
    "回复规则：\n"
    "1. 用口语化、亲切的中文回复，像朋友聊天一样自然\n"
    "2. 回复长度控制在 1-4 句话，不要过长\n"
    "3. 在回复中任意位置插入情绪标签 {emotion_xxx} 来切换表情\n"
    "   可选情绪：{{emotions}}\n"
    "   同一句话中可以多次使用不同标签\n"
    "4. 不要在标签前后加任何多余文字\n"
    "5. 你的回复中不应包含括号中的心理活动描写，直接说话即可\n"
    "6. 你只能输出纯文本对话，禁止调用任何工具/函数，禁止输出图片/文件/附件"
)

EXPRESSION_KEYS = ["neutral", "happy", "sad", "angry", "surprised", "blush", "thinking"]


def get_emotion_tags(config: dict) -> list[str]:
    expressions = config.get("expressions", {})
    if not isinstance(expressions, dict):
        expressions = {}
    keys = [k for k in expressions if k]

    custom_raw = config.get("custom_emotions", "")
    if custom_raw and isinstance(custom_raw, str):
        try:
            custom = json.loads(custom_raw)
        except (json.JSONDecodeError, TypeError):
            custom = {}
        if isinstance(custom, dict):
            for k in custom:
                if k and k not in keys:
                    keys.append(k)

    if keys:
        return keys
    return list(DEFAULT_EMOTION_TAGS)


def extract_emotions(text: str, emotion_tags: list[str]) -> tuple[str, list]:
    segments = []
    emotions = []
    last_end = 0
    for m in EMOTION_PATTERN.finditer(text):
        tag = m.group(1).lower()
        if tag in emotion_tags:
            segments.append(text[last_end:m.start()])
            emotions.append((tag, sum(len(s) for s in segments)))
            last_end = m.end()
    segments.append(text[last_end:])
    clean = "".join(segments).strip()
    if not emotions:
        for tag in emotion_tags:
            p = re.compile(rf"\{{emotion_{re.escape(tag)}\}}", re.IGNORECASE)
            for m in p.finditer(text):
                emotions.append((tag.lower(), m.start()))
                clean = re.sub(rf"\{{emotion_{re.escape(tag)}\}}", "", text, flags=re.IGNORECASE).strip()
                break
            if emotions:
                break
    return clean, emotions
