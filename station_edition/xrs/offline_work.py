"""Offline heavy-task worker skeleton (multi-core safe).

设计目标
========
把“离线重任务”做成可独立加载的最小 worker 模块，与运行时装配命名空间
(runtime.py 的 exec 方式) 解耦，从而可以安全地放进 ProcessPoolExecutor(spawn)：
主进程只负责切分任务 -> 派发给 N 个 worker -> 收集结果 -> 由主进程合并写库。

本模块自身不依赖运行时全局(state_table/history_table/APP_CONFIG 等)，只 import
标准库与纯函数。需要外部只读数据(如机型前缀表)时通过参数显式传入，避免共享内存。

用法示例
========
python3 -m station_edition.xrs.offline_work            # 跑 4 核加速比自检
python3 -m station_edition.xrs.offline_work --workers 2
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
from concurrent.futures import ProcessPoolExecutor


def default_workers() -> int:
    """可用 worker 数：默认 = CPU 核心数，可用 XRS_OFFLINE_WORKERS 覆盖。"""
    try:
        env = int(os.environ.get("XRS_OFFLINE_WORKERS") or 0)
        if env > 0:
            return min(env, 64)
    except Exception:
        pass
    try:
        return max(1, int(mp.cpu_count() or 1))
    except Exception:
        return 1


def load_model_map(path: str) -> list[dict]:
    """读取纯只读机型映射表（rid_model.json 同构）。"""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    raw = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raw = data if isinstance(data, list) else []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            prefix = str(item.get("prefix") or "").upper().strip()
            name = str(item.get("model") or "").strip()
            if prefix and name:
                out.append({"prefix": prefix, "model": name})
    return out


# ---------------------------------------------------------------------------
# 纯函数：必须在模块顶层、可 pickle，且不能引用任何运行时全局。
# ---------------------------------------------------------------------------

def _identify_one(model: str, mapping: list[dict]) -> str:
    """对单个机型标识做前缀识别（当前为最朴素的纯 Python 线性扫描，用于压测）。"""
    text = str(model or "").upper()
    if not text or not mapping:
        return ""
    best = ""
    best_len = -1
    for row in mapping:
        prefix = row.get("prefix") or ""
        if text.startswith(prefix) and len(prefix) > best_len:
            best_len = len(prefix)
            best = row.get("model") or ""
    return best


_OW_WORKER_MAPPING: list[dict] = []

def _offline_worker_init(mapping: list[dict]) -> None:
    """进程初始化：每个 worker 只接收一次只读映射数据。"""
    global _OW_WORKER_MAPPING
    _OW_WORKER_MAPPING = mapping


def _identify_chunk(chunk: list[str], mapping: list[dict]) -> list[str]:
    """每个 worker 对一个样本块做识别，返回与 chunk 等长的结果。"""
    return [_identify_one(item, mapping) for item in chunk]


def _identify_chunk_no_map(chunk: list[str]) -> list[str]:
    """使用 worker 初始化注入的映射（避免每次任务重复序列化大表）。"""
    return [_identify_one(item, _OW_WORKER_MAPPING) for item in chunk]


def parallel_identify(samples: list[str], mapping: list[dict], workers: int | None = None) -> list[str]:
    """用 ProcessPoolExecutor(spawn) 并行识别，保持输入顺序。"""
    if not samples:
        return []
    n = max(1, int(workers or default_workers()))
    size = max(1, (len(samples) + n - 1) // n)
    chunks = [samples[i : i + size] for i in range(0, len(samples), size)]
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=len(chunks), mp_context=ctx, initializer=_offline_worker_init, initargs=(mapping,)) as pool:
        futures = [pool.submit(_identify_chunk_no_map, c) for c in chunks]
        results = [f.result() for f in futures]
    out: list[str] = []
    for part in results:
        out.extend(part)
    return out


# ---------------------------------------------------------------------------
# 自检基准：合成一批“机型标识 + 前缀表”，对比单进程与多进程耗时。
# ---------------------------------------------------------------------------

def run_benchmark(workers: int | None = None, samples_n: int = 60000, mapping_n: int = 4000) -> dict:
    mapping = [{"prefix": f"SIM{n:04d}", "model": f"Model {n}"} for n in range(mapping_n)]
    import random

    rng = random.Random(20260906)
    samples = [f"SIM{rng.randrange(mapping_n):04d}A{rng.randrange(1, 10)}" for _ in range(samples_n)]

    t0 = time.perf_counter()
    _ = _identify_chunk(samples, mapping)
    serial_ms = (time.perf_counter() - t0) * 1000.0

    w = max(1, int(workers or default_workers()))
    t0 = time.perf_counter()
    out = parallel_identify(samples, mapping, workers=w)
    parallel_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "samples": samples_n,
        "mapping": mapping_n,
        "workers": w,
        "serial_ms": round(serial_ms, 2),
        "parallel_ms": round(parallel_ms, 2),
        "speedup": round(serial_ms / max(parallel_ms, 0.001), 2),
        "out_len": len(out),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="离线多核 worker 自检")
    parser.add_argument("--workers", type=int, default=None, help="worker 数(默认 CPU 核数)")
    parser.add_argument("--samples", type=int, default=60000)
    parser.add_argument("--mapping", type=int, default=4000)
    args = parser.parse_args()
    result = run_benchmark(workers=args.workers, samples_n=args.samples, mapping_n=args.mapping)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
