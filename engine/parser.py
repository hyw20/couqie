from __future__ import annotations

import re
from dataclasses import dataclass, asdict

ACTION_ALIASES = {
    "挥手": "wave",
    "招手": "wave",
    "打招呼": "wave",
    "挥手告别": "wave",
    "走路": "walk",
    "走两步": "walk",
    "走": "walk",
    "鞠躬": "bow",
    "弯腰": "bow",
    "坐下": "sit",
    "坐下休息": "sit",
    "转圈": "spin",
    "转身": "spin",
    "跳": "jump",
    "跳跃": "jump",
    "跳一下": "jump",
    "待机": "idle",
    "站着": "idle",
    "休息": "idle",
    "点头": "nod",
    "摇头": "shake",
    "鼓掌": "clap",
    "抬手": "wave",
    "眨眼": "blink",
    "闭眼": "blink",
    "挤眼": "wink",
    "单眼眨": "wink",
    "微笑": "smile",
    "笑": "smile",
    "张嘴": "talk",
    "说话": "talk",
    "生气": "angry",
    "皱眉": "angry",
}

SPLIT_RE = re.compile(r"然后|接着|再|之后|，|,|；|;|。")


@dataclass
class StageAction:
    name: str
    frames: int = 24
    repeats: int = 1
    speed: float = 1.0


def _speed(text: str) -> float:
    if any(k in text for k in ("慢慢", "缓慢", "轻轻")):
        return 0.6
    if any(k in text for k in ("快速", "赶快", "急速", "猛")):
        return 1.6
    return 1.0


def _repeats(text: str) -> int:
    mapping = {"两": 2, "二": 2, "三": 3, "四": 4, "五": 5}
    m = re.search(r"([两二三四五\d]+)\s*(下|次|圈|步)", text)
    if not m:
        return 1
    raw = m.group(1)
    if raw in mapping:
        return mapping[raw]
    return max(1, min(6, int(raw)))


def parse_instruction(text: str) -> list[StageAction]:
    text = (text or "").strip()
    if not text:
        return [StageAction("idle", frames=36)]

    chunks = [c.strip() for c in SPLIT_RE.split(text) if c.strip()]
    if not chunks:
        chunks = [text]

    actions: list[StageAction] = []
    for chunk in chunks:
        matched = None
        for alias, name in sorted(ACTION_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
            if alias in chunk:
                matched = name
                break
        if not matched:
            continue
        speed = _speed(chunk)
        repeats = _repeats(chunk)
        base = 32 if matched in {"walk", "spin"} else 24
        frames = max(12, int(base / speed))
        actions.append(StageAction(name=matched, frames=frames, repeats=repeats, speed=speed))

    return actions or [StageAction("idle", frames=36)]


def actions_to_payload(actions: list[StageAction]) -> list[dict]:
    return [asdict(a) for a in actions]
