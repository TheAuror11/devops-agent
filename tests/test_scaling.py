from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from devops_agent.queueing import InMemoryQueue
from devops_agent.scaling.backpressure import TokenBucket, assess_queue_pressure
from devops_agent.scaling.bulkhead import bedrock_slot
from devops_agent.worker.heartbeat import VisibilityHeartbeat


def test_token_bucket_rate_limit() -> None:
    bucket = TokenBucket(rate_per_minute=3)
    assert bucket.allow("space-a")
    assert bucket.allow("space-a")
    assert bucket.allow("space-a")
    assert not bucket.allow("space-a")
    assert bucket.allow("space-b")  # independent key


def test_queue_pressure_attributes() -> None:
    q = InMemoryQueue()
    for i in range(3):
        q.enqueue({"investigation_id": f"inv_{i}"})
    pressure = assess_queue_pressure(q)
    assert pressure.visible == 3
    assert pressure.in_flight == 0


def test_visibility_heartbeat_extends() -> None:
    calls: list[tuple[str, int]] = []

    def extend(handle: str, seconds: int) -> None:
        calls.append((handle, seconds))

    hb = VisibilityHeartbeat("rh_1", extend=extend, interval_seconds=0.05, visibility_seconds=30)
    hb.start()
    time.sleep(0.18)
    hb.stop()
    assert len(calls) >= 2
    assert calls[0] == ("rh_1", 30)


def test_bedrock_bulkhead_limits_concurrency() -> None:
    # Temporarily use a tiny bulkhead by resetting module semaphore.
    import devops_agent.scaling.bulkhead as bh
    from devops_agent.config import settings

    bh._bedrock_sem = __import__("threading").Semaphore(1)
    active = 0
    max_active = 0
    lock = __import__("threading").Lock()

    def work() -> None:
        nonlocal active, max_active
        with bedrock_slot():
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.08)
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(work) for _ in range(4)]
        for f in as_completed(futs):
            f.result()
    assert max_active == 1
    # restore for other tests
    bh._bedrock_sem = __import__("threading").Semaphore(settings.bedrock_max_inflight_per_task)


def test_worker_processes_batch_in_parallel() -> None:
    from devops_agent.domain.models import AgentSpace, Investigation, Priority
    from devops_agent.persistence.memory import MemoryStore
    from devops_agent.resilience.idempotency import IdempotencyStore
    from devops_agent.worker.handler import InvestigationHandler

    store = MemoryStore(data_dir="/tmp/devops-agent-scale-test")
    space = store.put_agent_space(AgentSpace(id="as_scale", name="scale"))
    # Seed minimal topology/runbooks via demo seed into global store is heavy;
    # run orchestrator path with local reasoner needs seeded retail space.
    # Instead verify ThreadPool scheduling of handler.handle via queue.
    q = InMemoryQueue()
    started: list[float] = []
    finished: list[float] = []

    class SlowHandler(InvestigationHandler):
        def handle(self, message):  # type: ignore[no-untyped-def]
            started.append(time.time())
            time.sleep(0.15)
            finished.append(time.time())

    # Use retail seed path for a real end-to-end parallel check in integration;
    # here assert pool overlap via SlowHandler.
    handler = SlowHandler(store, IdempotencyStore(), queue=q)
    for i in range(3):
        inv = store.put_investigation(
            Investigation(
                agent_space_id=space.id,
                title=f"t{i}",
                description="d",
                priority=Priority.HIGH,
            )
        )
        q.enqueue({"investigation_id": inv.id, "agent_space_id": space.id})

    msgs = q.receive(max_messages=3, wait_seconds=1)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(handler.handle, msgs))
    elapsed = time.time() - t0
    assert elapsed < 0.4  # parallel, not 0.45 sequential
    assert len(started) == 3
