from __future__ import annotations

REWARD_GEMS = 100

SCENARIOS = {
    "duplicate_request": {
        "title": "重复请求",
        "description": "同一幂等键连续提交两次，只应创建一张订单、一条 Outbox 事件和一笔账本流水。",
    },
    "acknowledgement_loss": {
        "title": "确认丢失后重试",
        "description": "Outbox 轮询首次入账后模拟未确认；再次轮询不得重复增加余额。",
    },
    "concurrent_consume": {
        "title": "并行消费尝试",
        "description": "两个独立 Outbox 轮询任务同时发现同一待消费事件；账本唯一约束只允许一笔入账。",
    },
    "guard_disabled_control": {
        "title": "账本守卫失效对照",
        "description": "阴性对照：故意跳过账本写入，验证断言能检出重复余额副作用。",
    },
}


def available_reliability_scenarios() -> list[dict[str, str]]:
    """Return the public scenario metadata exposed by the reliability API."""
    return [{"code": code, **metadata} for code, metadata in SCENARIOS.items()]
