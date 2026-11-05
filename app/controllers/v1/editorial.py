"""Structured editorial endpoints for external Python automation."""

from uuid import UUID, uuid4

from fastapi import Depends, Request
from filelock import FileLock, Timeout

from app.controllers import base
from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.v1.base import new_router
from app.controllers.v1.video import task_manager
from app.models import const
from app.models.editorial import (
    DecompositionRequest, EditorialScriptRequest, ResearchRequest, WorkflowRequest,
)
from app.models.exception import HttpException
from app.models.schema import BaseResponse
from app.services import editorial, reference_research
from app.services import state as sm
from app.utils import utils

router = new_router(dependencies=[Depends(base.verify_token)])


def _service_error(request, exc):
    status = 503 if isinstance(exc, reference_research.ResearchError) else 400
    if str(exc).startswith(("invalid_editorial_decision", "invalid_script")):
        status = 502
    return HttpException(task_id=base.get_task_id(request), status_code=status, message=str(exc))


@router.post("/editorial/research", response_model=BaseResponse)
def research(request: Request, body: ResearchRequest):
    try:
        return utils.get_response(200, editorial.research(body))
    except editorial.EditorialError as exc:
        raise _service_error(request, exc) from exc


@router.post("/editorial/decompose", response_model=BaseResponse)
def decompose(request: Request, body: DecompositionRequest):
    try:
        findings = editorial.research(body)
        settings = editorial.config.snapshot_config_with_pending(editorial.config.app)
        decision = editorial.decompose(body, findings=findings, app_config=settings)
        return utils.get_response(200, {
            "research": findings, "decision": decision.model_dump(),
            "selected_adaptation": decision.selected.model_dump(), "approval": "ai_selected",
        })
    except (editorial.EditorialError, reference_research.ResearchError) as exc:
        raise _service_error(request, exc) from exc


@router.post("/editorial/scripts", response_model=BaseResponse)
def script(request: Request, body: EditorialScriptRequest):
    try:
        findings = editorial.research(body)
        settings = editorial.config.snapshot_config_with_pending(editorial.config.app)
        text = editorial.generate_script(body, body.decision, findings=findings, app_config=settings)
        return utils.get_response(200, {
            "script": text, "selected_adaptation": body.decision.selected.model_dump(),
            "video_params": editorial.video_params(body, body.decision, text),
        })
    except (editorial.EditorialError, reference_research.ResearchError) as exc:
        raise _service_error(request, exc) from exc


def submit_workflow(body):
    workflow_id = str(body.workflow_id or uuid4())
    directory = editorial.workflow_dir(workflow_id)
    try:
        with FileLock(str(directory / "submission.lock")).acquire(timeout=1):
            existing = editorial.read_workflow(workflow_id)
            if existing and existing["fingerprint"] != editorial.fingerprint(body):
                raise editorial.EditorialError("workflow_id_conflict")
            if existing and (existing.get("state") == const.TASK_STATE_COMPLETE or editorial.is_running(workflow_id)):
                return workflow_id
            # Deduplicate queued submissions in this running instance. After a
            # memory-state restart the missing state allows explicit resubmission.
            state = sm.state.get_task(workflow_id)
            if state and state.get("kind") != "editorial":
                raise editorial.EditorialError("workflow_id_conflict")
            if existing and existing.get("stage") == "queued" and state and state.get("state") == const.TASK_STATE_PROCESSING:
                return workflow_id
            previous = existing
            if existing is None:
                existing = {"workflow_id": workflow_id, "fingerprint": editorial.fingerprint(body),
                            "kind": "editorial", "stage": "queued", "progress": 0,
                            "state": const.TASK_STATE_PROCESSING, "provider": body.provider}
                editorial._save(directory, existing)
            sm.state.update_task(workflow_id, kind="editorial", stage="queued")
            try:
                task_manager.add_task(editorial.start_editorial, task_id=workflow_id, params=body)
            except Exception:
                if previous is None:
                    (directory / "workflow.json").unlink(missing_ok=True)
                    sm.state.delete_task(workflow_id)
                else:
                    sm.state.update_task(workflow_id, kind="editorial", state=const.TASK_STATE_FAILED,
                                         failed_stage="scheduling", error="workflow_scheduling_failed")
                raise
            return workflow_id
    except Timeout as exc:
        raise editorial.EditorialError("workflow_submission_busy") from exc


@router.post("/editorial/workflows", status_code=202, response_model=BaseResponse)
def create_workflow(request: Request, body: WorkflowRequest):
    try:
        workflow_id = submit_workflow(body)
        return utils.get_response(202, {
            "workflow_id": workflow_id,
            "status_url": f"/api/v1/editorial/workflows/{workflow_id}",
        })
    except TaskQueueFullError as exc:
        raise HttpException(task_id=base.get_task_id(request), status_code=429, message="task queue is full") from exc
    except editorial.EditorialError as exc:
        raise HttpException(task_id=base.get_task_id(request), status_code=409, message=str(exc)) from exc


@router.get("/editorial/workflows/{workflow_id}", response_model=BaseResponse)
def get_workflow(request: Request, workflow_id: UUID):
    payload = editorial.read_workflow(workflow_id)
    if payload is None:
        raise HttpException(task_id=base.get_task_id(request), status_code=404, message="workflow not found")
    result = editorial.public_result(payload)
    if (result.get("state") == const.TASK_STATE_PROCESSING and result.get("stage") != "queued"
            and not editorial.is_running(workflow_id)):
        result.update(interrupted=True, recovery="resubmit the same workflow_id and input to resume")
    return utils.get_response(200, result)
