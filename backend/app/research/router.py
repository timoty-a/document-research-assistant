"""Bounded JSON inputs; synchronous SQL/search/network operations run in workers."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.research import service
from app.research.provider import ResearchError
from app.research.schemas import Answer, Passage, Question

router = APIRouter(tags=['research'])


async def question_input(request):
    if request.query_params:
        raise ResearchError(422, 'invalid_question', 'Provide the question and selected document IDs only.')
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise ResearchError(415, 'unsupported_media_type', 'Use application/json.')
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > 8192:
                raise ResearchError(413, 'question_too_large', 'Question request exceeds 8 KiB.')
            body.extend(chunk)
        return Question.model_validate_json(body)
    except (ValueError, ValidationError, UnicodeError, RecursionError):
        raise ResearchError(422, 'invalid_question', 'Use a non-empty question of at most 1,000 characters and one to five unique document IDs.') from None
    finally:
        body.clear()


@router.get('/research/status')
def status(request: Request):
    settings = request.app.state.settings
    return {'enabled': settings.ai_enabled, 'provider': 'Groq' if settings.ai_enabled else None,
            'model': 'openai/gpt-oss-120b' if settings.ai_enabled else None}


async def perform(request, synthesize):
    value = await question_input(request)
    state = request.app.state
    return await run_in_threadpool(service.answer, state.engine, state.settings, request.state.identity.token_digest,
                                   request.headers.get('x-csrf-token'), state.clock, value,
                                   synthesize=synthesize, generator=state.research_generator)


@router.post('/research/search', response_model=Answer)
async def search(request: Request):
    return await perform(request, False)


@router.post('/research/questions', response_model=Answer)
async def ask(request: Request):
    return await perform(request, True)


@router.get('/documents/{document_id}/passage', response_model=Passage)
def passage(request: Request, document_id: UUID,
            start: Annotated[int, Query(ge=0, le=1048576)],
            end: Annotated[int, Query(ge=1, le=1048576)],
            version: Annotated[str, Query(min_length=1, max_length=100)],
            page: Annotated[int, Query(ge=0, le=100)] = 0):
    state = request.app.state
    return service.passage(state.engine, state.settings, request.state.identity.token_digest, state.clock,
                           document_id, page, start, end, version)
