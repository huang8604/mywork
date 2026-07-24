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
    VersionRequest,
    WordAudioBatchGenerateRequest,
    WordAudioGenerateRequest,
    WordAudioRegenerateAllRequest,
    WordCreate,
    WordEnrichRequest,
    WordUpdate,
)
from app.services.audio_worker import enqueue_audio_generation
from app.services.dictionary import enrich_preview, enrich_word
from app.services.idempotency import claim, complete
from app.services.serializers import word_data
from app.services.tts import audio_providers_info
from app.services.words import (
    SORTS,
    create_word,
    delete_word,
    generate_missing_word_audio,
    generate_word_audio,
    get_word,
    iter_words,
    list_words,
    non_deleted_word_ids,
    reimport_word,
    reset_word_progress,
    restore_word,
    update_word,
    word_audio_file,
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


def _begin_import_transaction(db: Session) -> None:
    if db.get_bind().dialect.name != "sqlite":
        return
    if db.in_transaction():
        db.rollback()
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


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
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
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
    input_total = len(payloads)
    _begin_import_transaction(db)
    idem_payload = {
        "sha256": __import__("hashlib").sha256(raw).hexdigest(),
        "conflict_policy": conflict_policy,
        "unresolved_policy": unresolved_policy,
        "dry_run": dry_run,
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
    created = updated = skipped = dictionary_matches = 0
    resolved: list[dict] = []
    unresolved_details: list[dict[str, object]] = []
    unresolved_words: list[str] = []
    seen: set[str] = set()
    # normalized → word_id of the first in-file occurrence, so a later duplicate
    # (under conflict_policy=skip) can report the same word_id rather than null.
    seen_ids: dict[str, int | None] = {}
    from app.services.domain import normalize_word

    for row_number, payload in enumerate(payloads, 1):
        _, normalized = normalize_word(payload.en_word)
        if normalized in seen:
            # "skip" honors its name: dedupe within the file (first occurrence wins,
            # repeats counted as skipped). reject/update still treat an in-file
            # duplicate as a conflict and abort the whole batch atomically.
            if conflict_policy == "skip":
                skipped += 1
                resolved.append(
                    {
                        "en_word": payload.en_word,
                        "word_id": seen_ids.get(normalized),
                        "action": "skipped",
                    }
                )
                continue
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "导入文件内存在重复单词",
                [{"path": ["file", row_number, "en_word"], "reason": "归一化后与文件内其他单词重复"}],
            )
        seen.add(normalized)
        existing = db.scalar(select(Word).where(Word.normalized_en_word == normalized))
        # A skipped duplicate is resolved before any dictionary or AI lookup.
        # This avoids spending remote calls on a row that cannot change data.
        if existing is not None and existing.deleted_at is None:
            if conflict_policy == "reject":
                raise AppError(409, "DUPLICATE_WORD", "导入内容包含已存在的单词")
            if conflict_policy == "skip":
                skipped += 1
                seen_ids[normalized] = existing.id
                resolved.append(
                    {
                        "en_word": payload.en_word,
                        "word_id": existing.id,
                        "action": "skipped",
                    }
                )
                continue
        try:
            payload, found = enrich_word(payload, allow_ai=unresolved_policy == "ai")
            dictionary_matches += int(found)
        except AppError as exc:
            if exc.code != "DICTIONARY_ENTRY_NOT_FOUND":
                raise
            if unresolved_policy in {"skip", "ai"}:
                unresolved_words.append(payload.en_word)
                seen_ids[normalized] = None
                resolved.append(
                    {
                        "en_word": payload.en_word,
                        "word_id": None,
                        "action": "unresolved",
                    }
                )
                continue
            unresolved_details.append(
                {
                    "path": ["file", row_number, "en_word"],
                    "reason": "词典未收录该词，请手动填写中文释义",
                    "value": payload.en_word,
                }
            )
            continue
        if existing is None:
            new_id: int | None = None
            if not dry_run:
                new_id = create_word(db, payload).id
            created += 1
            seen_ids[normalized] = new_id
            resolved.append({"en_word": payload.en_word, "word_id": new_id, "action": "created"})
            continue
        if existing.deleted_at:
            # Re-importing a soft-deleted word restores it (undelete + refresh),
            # regardless of conflict_policy — bringing a deleted word back is the
            # explicit intent of importing it again. The unique normalized_en_word
            # constraint guarantees `existing` is the only matching row.
            if not dry_run:
                reimport_word(db, existing.id, payload)
            updated += 1
            seen_ids[normalized] = existing.id
            resolved.append({"en_word": payload.en_word, "word_id": existing.id, "action": "updated"})
            continue
        if not dry_run:
            update_word(
                db,
                existing.id,
                WordUpdate(**payload.model_dump(), expected_version=existing.version),
            )
        updated += 1
        seen_ids[normalized] = existing.id
        resolved.append({"en_word": payload.en_word, "word_id": existing.id, "action": "updated"})
    if unresolved_details:
        raise AppError(
            422,
            "DICTIONARY_ENTRY_NOT_FOUND",
            "部分单词无法获取释义",
            unresolved_details,
        )
    data = {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "rejected": 0,
        "unresolved": len(unresolved_words),
        "unresolved_words": unresolved_words,
        "resolved": resolved,
        "total": input_total,
        "dry_run": dry_run,
        "dictionary_matches": dictionary_matches,
    }
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
    logger.info(
        "word_import request_id=%s total=%s created=%s updated=%s skipped=%s unresolved=%s dictionary_matches=%s dry_run=%s",
        _request_id(request),
        data["total"],
        data["created"],
        data["updated"],
        data["skipped"],
        data["unresolved"],
        data["dictionary_matches"],
        data["dry_run"],
    )
    _commit(db)
    settings = get_settings()
    if (
        not dry_run
        and settings.tts_auto_generate_on_import
        and (settings.tts_enabled or settings.volc_enabled)
    ):
        created_ids = [
            r["word_id"]
            for r in resolved
            if r.get("action") == "created" and r.get("word_id")
        ]
        queued = enqueue_audio_generation(created_ids, force=False)
        data["audio_generation"] = {"queued": queued}
    return envelope(request, data)


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


@router.get("/audio/providers")
def audio_providers(
    request: Request,
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
):
    return envelope(request, audio_providers_info())


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
    data = generate_missing_word_audio(db, limit=payload.limit, provider=payload.provider)
    complete(idem, data=data, status_code=200, resource_type="word_audio_batch")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="word_audio.generate_missing",
        outcome="success",
        http_status=200,
        metadata={
            key: data[key]
            for key in ("requested", "generated", "failed", "has_more")
        },
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


@router.get("/{word_id}/audio")
def get_audio(
    word_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("words:read"))],
):
    word = get_word(db, word_id)
    audio = word_audio_file(word)
    if audio is None:
        raise AppError(404, "AUDIO_NOT_FOUND", "音频尚未生成")
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
    word = generate_word_audio(db, word_id, force=payload.force, provider=payload.provider)
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
