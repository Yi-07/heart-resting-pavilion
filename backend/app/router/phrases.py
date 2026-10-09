"""预设话术库(backend-plan §2 router 行):场景×情绪组织,不经 LLM。

安全话术(危机)固定文案,确定性,绝不走 LLM;安抚语按场景取用。
危机黑板帧文案(scene_crisis note)在此单源;stage_map 测试模板数据在前端 templates.ts。
"""

from app.schema import MoodKey

# ---- 危机序列(契约 §6.3) ----

CRISIS_SOOTHE = "我在,我在认真听。你现在很安全,这段时间真的太不容易了。"

CRISIS_HOTLINE = (
    "如果你现在有伤害自己的念头,请立刻拨打全国心理援助热线 12356(24 小时),"
    "或者告诉身边一位你能信任的人。这件事不需要你一个人扛,专业的人帮得到你。"
)

# 危机黑板帧(blackboard-v1 定稿):scene_crisis 固定场景,note 单源在此。
# stage_map 保留为测试模板,危机链路不再使用(数据保留于 frontend templates.ts)。
CRISIS_SCENE_NOTE = "你不是一个人"

# ---- 心情选择(契约 §4.2 独立到达的短安抚) ----

MOOD_ACK: dict[MoodKey, str] = {
    "难过": "抱抱,难过的时候不用急着好起来,我陪着你。",
    "低落": "嗯,低落就低落一会儿吧,这不丢人。",
    "平静": "平静挺好,给自己留一点这样的时刻。",
    "还好": "还好就好,慢慢来。",
    "开心": "开心的时候值得被记住,笑一个。",
    "很好": "真好呀,把这份好心情多留一会儿。",
}

# ---- answer 降级(LLM 失败/超时,backend-plan §2 llm 行) ----

ANSWER_FALLBACK = "这句话我一时答不上来,但我在。可以换个说法再问我,或者跟我说说你现在的感受。"

# ---- collect 采集话术(spec §4 L4:第一帧按情绪标签选;LLM 只润色,MVP 用库) ----

SOOTHE_BY_LABEL: dict[str, str] = {
    "焦虑": "先别急,慢慢说。焦虑缠着人的时候,能开口讲出来已经不容易。",
    "低落": "嗯,我在听。低落不需要马上被解释,先让它被看见。",
    "疲惫": "辛苦了。撑了这么久,这里可以先放一放。",
}
SOOTHE_DEFAULT = "嗯,我在听。你说,我陪着你。"
SOOTHE_CARRY = "好,我们重新开始梳理这一件——你慢慢说,我在。"


def collect_soothe(label: str | None, *, carried: bool) -> str:
    """冷启动按标签选;抢占/重启用承接变体。"""
    if carried:
        return SOOTHE_CARRY
    return SOOTHE_BY_LABEL.get(label or "", SOOTHE_DEFAULT)


CONFIRM_BY_FIELD: dict[str, str] = {
    "situation": "嗯,那件事我记下了。",
    "emotion": "好,我听见这份感受了。",
    "thought": "谢谢你愿意说出来,这个念头很重要。",
    "behavior": "嗯,当时的你已经在用自己的方式应对了。",
    "intermediate_belief": "这个联系我记下来了,很关键。",
    "core_belief": "你说的这句,我会认真放着。",
}
RETRY_ACK = "刚才那句有点短,不怕,再说一次就好——"
EMPATH_CHAT_REPLY = "嗯,我听着呢。你想到哪说到哪,我们慢慢来。"
SUMMARY_FALLBACK = (
    "这次的梳理我先记在这里了。整理的话没组织好,但你说的每一句我都收到了——"
    "我们下次接着聊。"
)
STATION_INVITE = (
    "我把这次的梳理放进了右侧的「心灵补给站」,里面有一份为你整理的小方案,"
    "想看的时候随时点开。"
)
