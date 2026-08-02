from __future__ import annotations

import csv
import io
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import add_audit
from app.core.auth import Actor, require_scopes
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.responses import envelope
from app.models import Word
from app.schemas import (
    BatchAudioRequest,
    BatchDeleteRequest,
    BatchTagsRequest,
    BatchWordIdsRequest,
    NumberAudioGenerateRequest,
    VersionRequest,
    WordAudioBatchGenerateRequest,
    WordAudioGenerateRequest,
    WordAudioRegenerateAllRequest,
    WordCreate,
    WordEnrichRequest,
    WordUpdate,
)
from app.services.audio_worker import (
    audio_progress,
    enqueue_audio_generation,
    enqueue_number_generation,
)
from app.services.dictionary import enrich_preview, enrich_word
from app.services.domain import normalize_word
from app.services.idempotency import claim, complete
from app.services.import_worker import enqueue_import, import_progress, run_import_row
from app.services.number_audio import NUMBER_MAX, missing_number_pairs
from app.services.serializers import word_data
from app.services.tts import audio_providers_info
from app.services.words import (
    SORTS,
    batch_add_tags,
    batch_delete_words,
    batch_reset_progress,
    create_word,
    delete_word,
    enqueue_missing_word_audio,
    generate_word_audio_pair,
    get_word,
    iter_words,
    list_words,
    merge_default_tags,
    non_deleted_word_ids,
    reset_word_progress,
    restore_word,
    update_word,
    word_audio_file,
    word_chinese_audio_file,
)

router = APIRouter(prefix="/api/v1/words", tags=["words"])
logger = logging.getLogger("word_memory.words")


def _request_id(request: Request) -> str:
    return request.state.request_id


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


@router.post("")
def create(
    request: Request,
    payload: WordCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 201,
            headers={"Idempotency-Replayed": "true"},
        )
    payload, dictionary_found = enrich_word(payload, allow_ai=get_settings().ai_enabled)
    word = create_word(db, payload)
    data = word_data(db, word)
    complete(idem, data=data, status_code=201, resource_type="word", resource_id=word.id)
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.create",
        outcome="success",
        http_status=201,
        target_type="word",
        target_id=word.id,
        metadata={"dictionary_found": dictionary_found},
    )
    _commit(db)
    return envelope(request, data, status_code=201)


@router.post("/enrich")
def enrich(
    request: Request,
    payload: WordEnrichRequest,
    _actor: Annotated[Actor, Depends(require_scopes("words:write"))],
):
    return envelope(request, [enrich_preview(word, allow_ai=payload.allow_ai) for word in payload.words])


@router.get("")
def index(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    keyword: str | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    is_custom: bool | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    sort: str = "created_at_desc",
):
    if sort not in SORTS:
        raise AppError(422, "VALIDATION_ERROR", "不支持的排序方式")
    if created_from and created_to and created_from > created_to:
        raise AppError(422, "VALIDATION_ERROR", "创建开始日期不能晚于结束日期")
    words, total = list_words(
        db,
        page=page,
        size=size,
        keyword=keyword,
        tags=tag or [],
        is_custom=is_custom,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
    )
    return envelope(
        request,
        [word_data(db, word) for word in words],
        meta={"page": page, "size": size, "total": total},
    )


@router.get("/export")
def export_words(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("words:export"))],
    format: str = "csv",
    keyword: str | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    is_custom: bool | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    sort: str = "created_at_desc",
):
    if format not in {"csv", "json"}:
        raise AppError(422, "VALIDATION_ERROR", "导出格式必须是 csv 或 json")
    if sort not in SORTS:
        raise AppError(422, "VALIDATION_ERROR", "不支持的排序方式")
    if created_from and created_to and created_from > created_to:
        raise AppError(422, "VALIDATION_ERROR", "创建开始日期不能晚于结束日期")

    def words():
        return iter_words(
            db,
            keyword=keyword,
            tags=tag or [],
            is_custom=is_custom,
            created_from=created_from,
            created_to=created_to,
            sort=sort,
        )

    headers = {
        "Content-Disposition": f'attachment; filename="words.{format}"',
        "X-Content-Type-Options": "nosniff",
    }
    if format == "json":
        return StreamingResponse(
            _stream_json_export(db, words()),
            media_type="application/json",
            headers=headers,
        )
    return StreamingResponse(
        _stream_csv_export(db, words()),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


def _stream_json_export(db: Session, words):
    yield "[\n"
    first = True
    for word in words:
        if not first:
            yield ",\n"
        first = False
        yield json.dumps(
            word_data(db, word, include_stats=False),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    yield "\n]\n"


def _stream_csv_export(db: Session, words):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["en_word", "phonetic", "cn_meaning", "example_sentence", "is_custom", "tags"]
    )
    yield "\ufeff" + output.getvalue()
    for word in words:
        item = word_data(db, word, include_stats=False)
        output.seek(0)
        output.truncate(0)
        row = [
            item["en_word"],
            item["phonetic"] or "",
            item["cn_meaning"],
            item["example_sentence"] or "",
            str(item["is_custom"]).lower(),
            ";".join(item["tags"]),
        ]
        writer.writerow([_safe_csv(value) for value in row])
        yield output.getvalue()


def _safe_csv(value: object) -> object:
    if isinstance(value, str):
        if value.startswith("'"):
            return "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
    return value


def _decode_safe_csv(value: str) -> str:
    if value.startswith("''"):
        return value[1:]
    if value.startswith("'") and value[1:].lstrip().startswith(("=", "+", "-", "@")):
        return value[1:]
    return value


@router.post("/import")
async def import_words(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    file: Annotated[UploadFile, File()],
    conflict_policy: Annotated[str, Form()] = "update",
    unresolved_policy: Annotated[str, Form()] = "ai",
    dry_run: Annotated[bool, Form()] = False,
    tags: Annotated[str, Form()] = "",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Import words.

    ``dry_run`` returns a synchronous no-write preview. A real import is
    enqueued to the background worker — each row committed independently, per-row
    errors skipped — and the current progress snapshot is returned immediately
    (so a slow enrichment can never blow the browser timeout and lose the batch).
    ``tags`` is a comma-separated list of default tags unioned into every row.
    ``conflict_policy=reject`` is pre-scanned: any existing word refuses the
    import with zero writes before a job is enqueued.
    """
    if conflict_policy not in {"skip", "update", "reject"}:
        raise AppError(422, "VALIDATION_ERROR", "不支持的冲突处理策略")
    if unresolved_policy not in {"skip", "reject", "ai"}:
        raise AppError(422, "VALIDATION_ERROR", "不支持的未命中处理策略")
    raw = await file.read(get_settings().max_import_bytes + 1)
    if len(raw) > get_settings().max_import_bytes:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "导入文件过大")
    payloads = _parse_import(file.filename or "", file.content_type or "", raw)
    if len(payloads) > get_settings().max_import_rows:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "导入行数过多")
    default_tags = _parse_tags_field(tags)
    payloads = [merge_default_tags(p, default_tags) for p in payloads]
    input_total = len(payloads)
    # In-file duplicates are a parse-time user error. Under skip the worker
    # dedupes (first wins); under reject/update we refuse synchronously with a
    # clear error before enqueueing anything (matching the legacy behavior).
    _check_infile_duplicates(payloads, conflict_policy)

    idem_payload = {
        "sha256": __import__("hashlib").sha256(raw).hexdigest(),
        "conflict_policy": conflict_policy,
        "unresolved_policy": unresolved_policy,
        "dry_run": dry_run,
        "tags": default_tags,
    }
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/import",
        key=idempotency_key,
        payload=idem_payload,
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )

    if dry_run:
        data = _run_dry_run(db, payloads, conflict_policy, unresolved_policy)
        complete(idem, data=data, status_code=200, resource_type="word_import")
        add_audit(
            db,
            request_id=_request_id(request),
            actor=actor,
            action="word.import",
            outcome="success",
            http_status=200,
            metadata={
                key: data[key]
                for key in (
                    "created",
                    "updated",
                    "skipped",
                    "unresolved",
                    "total",
                    "dry_run",
                    "dictionary_matches",
                )
            },
        )
        _commit(db)
        return envelope(request, data)

    # Real import. reject → zero-write pre-scan; otherwise enqueue to background.
    if conflict_policy == "reject":
        _reject_prescan(db, payloads)  # raises DUPLICATE_WORD on any conflict

    enqueue_import(
        payloads,
        conflict_policy=conflict_policy,
        unresolved_policy=unresolved_policy,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        request_id=_request_id(request),
        idempotency_key=idempotency_key,
    )
    logger.info(
        "word_import request_id=%s total=%s conflict_policy=%s unresolved_policy=%s background=True",
        _request_id(request),
        input_total,
        conflict_policy,
        unresolved_policy,
    )
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.import",
        outcome="success",
        http_status=200,
        metadata={
            "total": input_total,
            "conflict_policy": conflict_policy,
            "unresolved_policy": unresolved_policy,
            "background": True,
        },
    )
    _commit(db)  # persists the idempotency claim + audit; the worker finalizes the claim
    return envelope(request, import_progress())


@router.get("/import/progress")
def import_progress_route(
    request: Request,
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
):
    return envelope(request, import_progress())


def _parse_tags_field(tags: str) -> list[str]:
    """Comma-separated tag string (CN comma accepted) → trimmed non-empty list."""
    return [
        value
        for value in (item.strip() for item in tags.replace("，", ",").split(","))
        if value
    ]


def _run_dry_run(
    db: Session,
    payloads: list[WordCreate],
    conflict_policy: str,
    unresolved_policy: str,
) -> dict:
    """Synchronous no-write preview. Reuses ``run_import_row(dry_run=True)`` so the
    predicted actions match what the background worker will actually do."""
    allow_ai = unresolved_policy == "ai"
    created = updated = skipped = dictionary_matches = 0
    resolved: list[dict] = []
    unresolved_words: list[str] = []
    seen: set[str] = set()
    for payload in payloads:
        _, normalized = normalize_word(payload.en_word)
        if normalized in seen:
            skipped += 1
            resolved.append(
                {"en_word": payload.en_word, "word_id": None, "action": "skipped"}
            )
            continue
        seen.add(normalized)
        result = run_import_row(
            db,
            payload,
            conflict_policy=conflict_policy,
            allow_ai=allow_ai,
            dry_run=True,
        )
        action = result["action"]
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "skipped":
            skipped += 1
        elif action == "unresolved":
            unresolved_words.append(payload.en_word)
        if result.get("dictionary_found"):
            dictionary_matches += 1
        resolved.append(result)
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "rejected": 0,
        "unresolved": len(unresolved_words),
        "unresolved_words": unresolved_words,
        "resolved": resolved,
        "total": len(payloads),
        "dry_run": True,
        "dictionary_matches": dictionary_matches,
    }


def _reject_prescan(db: Session, payloads: list[WordCreate]) -> None:
    """conflict_policy=reject: if any payload matches an existing non-deleted word,
    refuse the whole import before enqueueing (zero writes). Soft-deleted words are
    not conflicts — they get restored (reimported) by the worker as usual."""
    norms: list[str] = []
    for payload in payloads:
        _, normalized = normalize_word(payload.en_word)
        norms.append(normalized)
    if not norms:
        return
    hit = db.scalar(
        select(Word).where(
            Word.normalized_en_word.in_(norms), Word.deleted_at.is_(None)
        )
    )
    if hit is not None:
        raise AppError(
            409,
            "DUPLICATE_WORD",
            "导入内容包含已存在的单词",
            [
                {
                    "path": ["body", "en_word"],
                    "reason": f"已存在：{hit.en_word}",
                    "word_id": hit.id,
                }
            ],
        )


def _check_infile_duplicates(payloads: list[WordCreate], conflict_policy: str) -> None:
    """Under reject/update, refuse a file containing duplicate (normalized) words
    synchronously. Under skip the worker dedupes (first occurrence wins)."""
    if conflict_policy == "skip":
        return
    seen: set[str] = set()
    for row_number, payload in enumerate(payloads, 1):
        _, normalized = normalize_word(payload.en_word)
        if normalized in seen:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "导入文件内存在重复单词",
                [
                    {
                        "path": ["file", row_number, "en_word"],
                        "reason": "归一化后与文件内其他单词重复",
                    }
                ],
            )
        seen.add(normalized)


def _parse_import(filename: str, content_type: str, raw: bytes) -> list[WordCreate]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(422, "VALIDATION_ERROR", "导入文件必须是 UTF-8 编码") from exc
    adapter = TypeAdapter(list[WordCreate])
    try:
        if filename.lower().endswith(".json") or content_type == "application/json":
            return adapter.validate_python(json.loads(text))
        if filename.lower().endswith(".txt") or content_type.startswith("text/plain"):
            rows = [
                {"en_word": value.strip()}
                for value in text.splitlines()
                if value.strip() and not value.lstrip().startswith("#")
            ]
            return adapter.validate_python(rows)
        if not filename.lower().endswith(".csv") and "csv" not in content_type:
            raise AppError(415, "UNSUPPORTED_MEDIA_TYPE", "仅支持 TXT、CSV 和 JSON 文件")
        reader = csv.DictReader(io.StringIO(text))
        required = {
            "en_word",
            "phonetic",
            "cn_meaning",
            "example_sentence",
            "is_custom",
            "tags",
        }
        if set(reader.fieldnames or []) != required:
            raise AppError(422, "VALIDATION_ERROR", "CSV 表头无效")
        rows = []
        for row in reader:
            rows.append(
                {
                    "en_word": _decode_safe_csv(row["en_word"]),
                    "phonetic": _decode_safe_csv(row["phonetic"]) or None,
                    "cn_meaning": _decode_safe_csv(row["cn_meaning"]),
                    "example_sentence": _decode_safe_csv(row["example_sentence"]) or None,
                    "is_custom": row["is_custom"].strip().lower() in {"true", "1", "yes"},
                    "tags": [
                        _decode_safe_csv(item)
                        for item in _decode_safe_csv(row["tags"]).split(";")
                        if item
                    ],
                }
            )
        return adapter.validate_python(rows)
    except json.JSONDecodeError as exc:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "导入数据无效",
            [{"path": ["file", exc.lineno, exc.colno], "reason": exc.msg}],
        ) from exc
    except ValidationError as exc:
        details = []
        for error in exc.errors():
            location = list(error["loc"])
            if location and isinstance(location[0], int):
                location[0] += 1
            details.append(
                {
                    "path": ["file", *location],
                    "reason": error["msg"],
                }
            )
        raise AppError(422, "VALIDATION_ERROR", "导入数据无效", details) from exc


@router.post("/batch/delete")
def batch_delete(
    request: Request,
    payload: BatchDeleteRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Soft-delete each word by id + expected_version. Per-word conflicts/missing
    are collected and reported; the batch always partial-succeeds."""
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/batch/delete",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    items = [item.model_dump() for item in payload.items]
    data = batch_delete_words(db, items)
    complete(idem, data=data, status_code=200, resource_type="word_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.batch_delete",
        outcome="success",
        http_status=200,
        metadata={
            "requested": len(items),
            "deleted": len(data["deleted"]),
            "conflicts": len(data["conflicts"]),
            "missing": len(data["missing"]),
        },
    )
    _commit(db)
    return envelope(request, data)


@router.post("/batch/tags")
def batch_tags(
    request: Request,
    payload: BatchTagsRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Union ``tags`` onto each word. Per-word conflicts/missing collected."""
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/batch/tags",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    items = [item.model_dump() for item in payload.items]
    data = batch_add_tags(db, items, payload.tags)
    complete(idem, data=data, status_code=200, resource_type="word_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.batch_tags",
        outcome="success",
        http_status=200,
        metadata={
            "requested": len(items),
            "updated": len(data["updated"]),
            "conflicts": len(data["conflicts"]),
            "missing": len(data["missing"]),
            "tags": payload.tags,
        },
    )
    _commit(db)
    return envelope(request, data)


@router.post("/batch/audio")
def batch_audio(
    request: Request,
    payload: BatchAudioRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Enqueue selected words for paired English/Chinese MP3 generation."""
    settings = get_settings()
    if not (settings.tts_enabled or settings.volc_enabled):
        raise AppError(409, "TTS_NOT_CONFIGURED", "TTS 尚未配置")
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/batch/audio",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    queued = enqueue_audio_generation(payload.word_ids, force=False, provider=payload.provider)
    data = {"queued": queued, "total": len(payload.word_ids), "provider": payload.provider}
    complete(idem, data=data, status_code=200, resource_type="word_audio_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word_audio.batch_generate",
        outcome="success",
        http_status=200,
        metadata={"queued": queued, "total": len(payload.word_ids)},
    )
    _commit(db)
    return envelope(request, data)


@router.post("/batch/reset-progress")
def batch_reset(
    request: Request,
    payload: BatchWordIdsRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Clear review history for each id (back to the 新词 pool). Missing/deleted
    ids are skipped silently."""
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/batch/reset-progress",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    data = batch_reset_progress(db, payload.word_ids)
    complete(idem, data=data, status_code=200, resource_type="word_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.batch_reset_progress",
        outcome="success",
        http_status=200,
        metadata={"requested": len(payload.word_ids), "reset": data["reset"]},
    )
    _commit(db)
    return envelope(request, data)


@router.get("/audio/providers")
def audio_providers(
    request: Request,
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
):
    return envelope(request, audio_providers_info())


@router.get("/audio/progress")
def audio_progress_route(
    request: Request,
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
):
    return envelope(request, audio_progress())


@router.post("/audio/generate-missing")
def generate_missing_audio(
    request: Request,
    payload: WordAudioBatchGenerateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/audio/generate-missing",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    data = enqueue_missing_word_audio(db, limit=payload.limit, provider=payload.provider)
    complete(idem, data=data, status_code=200, resource_type="word_audio_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word_audio.generate_missing",
        outcome="success",
        http_status=200,
        metadata={"queued": data["queued"], "total": data["total"]},
    )
    _commit(db)
    return envelope(request, data)


@router.post("/audio/regenerate-all")
def regenerate_all_audio(
    request: Request,
    payload: WordAudioRegenerateAllRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/audio/regenerate-all",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=True,
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    word_ids = non_deleted_word_ids(db)
    queued = enqueue_audio_generation(word_ids, force=True, provider=payload.provider)
    data = {"queued": queued, "total": len(word_ids), "provider": payload.provider}
    complete(idem, data=data, status_code=200, resource_type="word_audio_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word_audio.regenerate_all",
        outcome="success",
        http_status=200,
        metadata={"queued": queued, "total": len(word_ids)},
    )
    _commit(db)
    return envelope(request, data)


@router.post("/audio/generate-numbers")
def generate_numbers_audio(
    request: Request,
    payload: NumberAudioGenerateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Generate paired English/Chinese number clips for positions 1 .. 50.

    豆包 preferred (provider defaults to volc); falls back to mimo via the worker.
    ``force`` regenerates all 1..50 pairs, otherwise pairs missing either language.
    Returns ``{queued, total, provider}``; progress via ``GET /words/audio/progress``.
    """
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/audio/generate-numbers",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    provider = payload.provider or "volc"
    if payload.force:
        nums = list(range(1, NUMBER_MAX + 1))
    else:
        nums = missing_number_pairs(limit=payload.limit)
    queued = enqueue_number_generation(nums, force=payload.force, provider=provider) if nums else 0
    data = {"queued": queued, "total": len(nums), "provider": provider}
    complete(idem, data=data, status_code=200, resource_type="number_audio_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="number_audio.generate",
        outcome="success",
        http_status=200,
        metadata={"queued": queued, "total": len(nums), "force": payload.force},
    )
    _commit(db)
    return envelope(request, data)


@router.get("/{word_id}/audio")
def get_audio(
    word_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
    language: Annotated[str, Query(pattern="^(en|zh)$")] = "en",
):
    word = get_word(db, word_id)
    audio = word_chinese_audio_file(word) if language == "zh" else word_audio_file(word)
    if audio is None:
        label = "中文" if language == "zh" else "英文"
        raise AppError(404, "AUDIO_NOT_FOUND", f"{label}音频尚未生成")
    return FileResponse(
        audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline"},
    )


@router.post("/{word_id}/audio")
def generate_audio(
    request: Request,
    word_id: int,
    payload: WordAudioGenerateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/words/{word_id}/audio",
        key=idempotency_key,
        payload={"word_id": word_id, **payload.model_dump(mode="json")},
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return envelope(
            request,
            idem.replay_data,
            status_code=idem.replay_status or 200,
            headers={"Idempotency-Replayed": "true"},
        )
    word = generate_word_audio_pair(
        db, word_id, force=payload.force, provider=payload.provider
    )
    data = word_data(db, word)
    complete(idem, data=data, status_code=200, resource_type="word", resource_id=word.id)
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word_audio.generate",
        outcome="success",
        http_status=200,
        target_type="word",
        target_id=word.id,
        metadata={"force": payload.force, "provider": payload.provider},
    )
    _commit(db)
    return envelope(request, data)


@router.get("/{word_id}")
def show(
    request: Request,
    word_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
):
    return envelope(request, word_data(db, get_word(db, word_id)))


@router.put("/{word_id}")
def update(
    request: Request,
    word_id: int,
    payload: WordUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
):
    word = update_word(db, word_id, payload)
    data = word_data(db, word)
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.update",
        outcome="success",
        http_status=200,
        target_type="word",
        target_id=word.id,
    )
    _commit(db)
    return envelope(request, data)


@router.delete("/{word_id}", status_code=204)
def destroy(
    request: Request,
    word_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    version = int(if_match.strip('"')) if if_match and if_match.strip('"').isdigit() else None
    deleted = delete_word(db, word_id, version)
    if deleted is not None:
        add_audit(
            db,
            request_id=_request_id(request),
            actor=actor,
            action="word.delete",
            outcome="success",
            http_status=204,
            target_type="word",
            target_id=word_id,
        )
    _commit(db)
    return Response(status_code=204)


@router.post("/{word_id}/restore")
def restore(
    request: Request,
    word_id: int,
    payload: VersionRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
):
    word = restore_word(db, word_id, payload.expected_version)
    data = word_data(db, word)
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.restore",
        outcome="success",
        http_status=200,
        target_type="word",
        target_id=word_id,
    )
    _commit(db)
    return envelope(request, data)


@router.post("/{word_id}/reset-progress")
def reset_progress(
    request: Request,
    word_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("words:write"))],
):
    word = reset_word_progress(db, word_id)
    data = word_data(db, word)
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word.reset_progress",
        outcome="success",
        http_status=200,
        target_type="word",
        target_id=word_id,
    )
    _commit(db)
    return envelope(request, data)
