"""Side-effect-free Celery task used to verify the code loaded by a worker."""

from src.worker.runtime_contract import build_worker_runtime_contract
from src.worker.tasks.summarize_task import summarize_transcript_task
from src.worker.worker import celery_app


@celery_app.task(bind=True, name="tasks.worker_runtime_contract")
def worker_runtime_contract_task(self) -> dict:
    contract = build_worker_runtime_contract(summarize_transcript_task.run)
    contract["worker_hostname"] = self.request.hostname
    return contract


__all__ = ["worker_runtime_contract_task"]
