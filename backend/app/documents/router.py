"""Multipart parsing dependency; file reads and database calls run in workers."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import Engine
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.documents import service
from app.documents.schemas import DocumentMetadata
from app.documents.validation import read_document

router = APIRouter(prefix="/documents", tags=["documents"])


async def single_file(request: Request, file: Annotated[UploadFile, File()]) -> UploadFile:
    # FastAPI has already parsed the form. This reads the cached form, not a
    # second copy of the body. Keep FastAPI's standard 422 for a missing file.
    form = await request.form()
    files = [value for _, value in form.multi_items() if isinstance(value, StarletteUploadFile)]
    if len(files) != 1 or len(form.getlist("file")) != 1:
        raise HTTPException(400, "Provide exactly one uploaded file named 'file'")
    return file


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


@router.post("", status_code=201, response_model=DocumentMetadata)
def upload_document(
    request: Request,
    file: Annotated[UploadFile, Depends(single_file)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> DocumentMetadata:
    document = read_document(file)
    try:
        return service.save_document(engine, request.app.state.settings, document)
    except service.DocumentStorageError:
        raise HTTPException(503, "Document storage is temporarily unavailable") from None


@router.get("", response_model=list[DocumentMetadata])
def get_documents(request: Request, engine: Annotated[Engine, Depends(get_engine)]) -> list[DocumentMetadata]:
    try:
        return service.list_documents(engine, request.app.state.settings)
    except service.DocumentStorageError:
        raise HTTPException(503, "Document storage is temporarily unavailable") from None
