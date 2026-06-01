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
    "3. 回复中用 {emotion_xxx} 标签标记情绪，格式固定为 {emotion_xxx}，emotion_ 前缀不可省略\n"
    "   每次情绪变化时输出两个标签（配对格式）：\n"
    "   - 第一个（必须在最前）：你自己发挥的自由情绪/语气/动作/状态，支持英文和中文\n"
    "     如 {emotion_excited}、{emotion_傲娇}、{emotion_whispering}、{emotion_偷笑} 等\n"
    "   - 第二个（紧跟在后面）：必须从以下立绘表情中选择一个：{{emotions}}\n"
    "   如果自由情绪和必选立绘表情名称相同，则只写一个标签即可\n"
    "   ✅ 配对：{emotion_excited}{emotion_happy}今天天气真好！{emotion_shy}{emotion_blush}谢谢主人~\n"
    "   ✅ 同名：{emotion_happy}今天天气真好！\n"
    "   ✅ 多次：{emotion_surprised}{emotion_surprised}真的吗？{emotion_偷笑}{emotion_happy}太棒了~\n"
    "   ❌ 错误：{emotion_excited}今天天气真好！        ← 缺少必选立绘表情\n"
    "   ❌ 错误：{emotion_happy}今天天气真好！           ← 缺少自由情绪（除非同名）\n"
    "   ❌ 错误：{happy}今天天气真好！                   ← 缺少 emotion_ 前缀\n"
    "   ❌ 错误：今天天气真好！(开心)                     ← 不能用括号写法\n"
    "4. 不要输出任何标签以外的东西，不要用括号写心理活动，直接说话\n"
    "5. 你只能输出纯文本对话，禁止调用任何工具/函数，禁止输出图片/文件/附件/emoji"
)

EXPRESSION_KEYS = ["neutral", "happy", "sad", "angry", "surprised", "blush", "thinking"]

VRM_EMOTION_MAP = {
    "neutral": "neutral",
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "surprised": "surprised",
    "blush": "relaxed",
    "thinking": "neutral",
}


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


def extract_all_emotions(text: str, known_tags: list[str]) -> tuple[str, list, list]:
    """Extract all {emotion_xxx} tags. Returns (clean_text, known_only, all_emotions)."""
    segments = []
    all_emotions = []
    last_end = 0
    for m in EMOTION_PATTERN.finditer(text):
        tag = m.group(1).lower()
        segments.append(text[last_end:m.start()])
        all_emotions.append((tag, sum(len(s) for s in segments)))
        last_end = m.end()
    segments.append(text[last_end:])
    clean = "".join(segments).strip()

    if not all_emotions:
        for tag in known_tags:
            p = re.compile(rf"\{{emotion_{re.escape(tag)}\}}", re.IGNORECASE)
            for m in p.finditer(text):
                all_emotions.append((tag.lower(), m.start()))
                clean = re.sub(rf"\{{emotion_{re.escape(tag)}\}}", "", text, flags=re.IGNORECASE).strip()
                break
            if all_emotions:
                break

    known = [(tag, pos) for tag, pos in all_emotions if tag in known_tags]
    return clean, known, all_emotions
