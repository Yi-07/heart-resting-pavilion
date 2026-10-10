"""自检:确认修正后的逐帧算法**能**抓到它要抓的模式。

上一版按「首次出现顺序」构造 order,结构上发现不了回退。这里用合成帧
验证新旧两种算法在同一输入上的判定差异,防止再次写出「永远为 0」的检测器。

跑法:
    D:\\miniconda3\\envs\\test\\python.exe tests/diag_round_order_selftest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from diag_round_order import analyze_frames  # noqa: E402


def old_algorithm_flag(frames: list[dict]) -> bool:
    """上一版的判据:按首次出现顺序找编号逆序。"""
    order: list[str] = []
    for f in frames:
        if f["round_id"] not in order:
            order.append(str(f["round_id"]))

    def num(r: str) -> int | None:
        t = r.rsplit("-", 1)[-1]
        return int(t) if t.isdigit() else None

    return any(
        num(order[i]) is not None
        and num(order[j]) is not None
        and num(order[i]) > num(order[j])
        for i in range(len(order))
        for j in range(i + 1, len(order))
    )


def case(name: str, frames: list[dict], expect_late: int) -> None:
    r = analyze_frames(frames)
    got = len(r["late_old_round_frames"])
    old = old_algorithm_flag(frames)
    ok = got == expect_late
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"        新算法检出迟到帧 {got} 条(期望 {expect_late}) / "
          f"旧算法判逆序 {old}")
    if got:
        for x in r["late_old_round_frames"]:
            print(f"          #{x['at_index']} t={x['t']} {x['from']} -> {x['to']} "
                  f"audio_seq={x['audio_seq']}")
    return ok


def f(rid: str, aseq: int, seq: int, t: float) -> dict:
    return {"round_id": rid, "audio_seq": aseq, "seq": seq, "t": t, "bytes": 3200}


def main() -> int:
    results = []

    # 任务书给的例子:新回合首帧之后又收到旧回合 PCM
    results.append(case(
        "任务书例子 tts-0/0 -> tts-1/0 -> tts-0/1",
        [f("tts-0", 0, 1, 0.0), f("tts-1", 0, 2, 0.5), f("tts-0", 1, 3, 0.9)],
        expect_late=1,
    ))

    # 正常两轮:新回合后不再有旧回合帧
    results.append(case(
        "正常两轮 tts-0(3块) -> tts-1(2块)",
        [f("tts-0", 0, 1, 0.0), f("tts-0", 1, 2, 0.1), f("tts-0", 2, 3, 0.2),
         f("tts-1", 0, 4, 0.5), f("tts-1", 1, 5, 0.6)],
        expect_late=0,
    ))

    # 更刁钻:三个回合交替穿插
    results.append(case(
        "三回合交替穿插",
        [f("tts-0", 0, 1, 0.0), f("tts-1", 0, 2, 0.1), f("tts-2", 0, 3, 0.2),
         f("tts-0", 1, 4, 0.3), f("tts-1", 1, 5, 0.4)],
        expect_late=2,
    ))

    # 只收到新回合(旧回合零帧)——抢占过早
    results.append(case(
        "抢占过早,旧回合零帧",
        [f("tts-1", 0, 1, 0.0), f("tts-1", 1, 2, 0.1)],
        expect_late=0,
    ))

    # audio_seq 缺号检测
    r = analyze_frames([f("tts-0", 0, 1, 0.0), f("tts-0", 2, 2, 0.1)])
    seq_ok = len(r["audio_seq_issues"]) == 1 and r["audio_seq_issues"][0]["missing"] == [1]
    print(f"[{'PASS' if seq_ok else 'FAIL'}] audio_seq 缺号被检出")
    if not seq_ok:
        print(f"        issues={r['audio_seq_issues']}")
    results.append(seq_ok)

    passed = sum(1 for x in results if x)
    print()
    print(f"自检 {passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())