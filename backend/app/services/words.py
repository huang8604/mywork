from __future__ import annotations

from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.models import Tag, Word, WordTag
from app.schemas import WordCreate, WordUpdate
from app.services.domain import normalize_tag, normalize_word, utc_text


def _duplicate_error(word: Word) -> AppError:
    if word.deleted_at:
        return AppError(
            409,
            "WORD_DELETED",
            "已存在相同拼写的已删除单词",
            [{"path": ["body", "en_word"], "reason": "可恢复该已删除的单词", "word_id": word.id}],
        )
    return AppError(409, "DUPLICATE_WORD", "该单词已存在")


def _set_tags(db: Session, word: Word, values: list[str]) -> None:
    db.query(WordTag).filter(WordTag.word_id == word.id).delete(synchronize_session=False)
    for value in values:
        display, normalized = normalize_tag(value)
        tag = db.scalar(select(Tag).where(Tag.normalized_name == normalized))
        if tag is None:
            tag = Tag(name=display, normalized_name=normalized)
            db.add(tag)
            db.flush()
        db.add(WordTag(word_id=word.id, tag_id=tag.id))


def create_word(db: Session, payload: WordCreate) -> Word:
    display, normalized = normalize_word(payload.en_word)
    duplicate = db.scalar(select(Word).where(Word.normalized_en_word == normalized))
    if duplicate is not None:
        raise _duplicate_error(duplicate)
    if not payload.cn_meaning:
        raise AppError(422, "VALIDATION_ERROR", "未能获取中文释义，请手动填写")
    now = utc_text()
    word = Word(
        en_word=display,
        normalized_en_word=normalized,
        phonetic=payload.phonetic,
        cn_meaning=payload.cn_meaning.strip(),
        example_sentence=payload.example_sentence,
        is_custom=int(payload.is_custom),
        created_at=now,
        updated_at=now,
    )
    db.add(word)
    db.flush()
    _set_tags(db, word, payload.tags)
    return word


def get_word(db: Session, word_id: int, *, include_deleted: bool = False) -> Word:
    word = db.get(Word, word_id)
    if word is None or (word.deleted_at and not include_deleted):
        raise not_found("word")
    return word


def update_word(db: Session, word_id: int, payload: WordUpdate) -> Word:
    word = get_word(db, word_id)
    if word.version != payload.expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "单词已被其他操作修改，请刷新后重试",
            [{"current_version": word.version}],
        )
    display, normalized = normalize_word(payload.en_word)
    duplicate = db.scalar(
        select(Word).where(
            Word.normalized_en_word == normalized,
            Word.id != word.id,
        )
    )
    if duplicate is not None:
        raise _duplicate_error(duplicate)
    word.en_word = display
    word.normalized_en_word = normalized
    word.phonetic = payload.phonetic
    word.cn_meaning = payload.cn_meaning.strip()
    word.example_sentence = payload.example_sentence
    word.is_custom = int(payload.is_custom)
    word.version += 1
    word.updated_at = utc_text()
    _set_tags(db, word, payload.tags)
    db.flush()
    return word


def delete_word(db: Session, word_id: int, expected_version: int | None) -> Word | None:
    word = db.get(Word, word_id)
    if word is None:
        raise not_found("word")
    if word.deleted_at:
        return None
    if expected_version is None or word.version != expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "单词已被其他操作修改，请刷新后重试",
            [{"current_version": word.version}],
        )
    now = utc_text()
    word.deleted_at = now
    word.updated_at = now
    word.version += 1
    db.flush()
    return word


def restore_word(db: Session, word_id: int, expected_version: int) -> Word:
    word = get_word(db, word_id, include_deleted=True)
    if word.version != expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "单词已被其他操作修改，请刷新后重试",
            [{"current_version": word.version}],
        )
    if word.deleted_at:
        word.deleted_at = None
        word.version += 1
        word.updated_at = utc_text()
        db.flush()
    return word


def reimport_word(db: Session, word_id: int, payload: WordCreate) -> Word:
    """Restore a soft-deleted word and overwrite it with an import payload.

    Importing a word whose normalized spelling matches a deleted word brings
    that word back instead of failing: undelete, refresh all fields from the
    payload, single version bump.
    """
    word = db.get(Word, word_id)
    if word is None:
        raise not_found("word")
    display, normalized = normalize_word(payload.en_word)
    word.en_word = display
    word.normalized_en_word = normalized
    word.phonetic = payload.phonetic
    word.cn_meaning = payload.cn_meaning.strip()
    word.example_sentence = payload.example_sentence
    word.is_custom = int(payload.is_custom)
    word.deleted_at = None
    word.version += 1
    word.updated_at = utc_text()
    _set_tags(db, word, payload.tags)
    db.flush()
    return word


SORTS = {
    "created_at_desc": (desc(Word.created_at), desc(Word.id)),
    "created_at_asc": (asc(Word.created_at), asc(Word.id)),
    "en_word_asc": (asc(Word.normalized_en_word), asc(Word.id)),
    "en_word_desc": (desc(Word.normalized_en_word), desc(Word.id)),
}


def list_words(
    db: Session,
    *,
    page: int,
    size: int,
    keyword: str | None,
    tags: list[str],
    is_custom: bool | None,
    created_from: str | None,
    created_to: str | None,
    sort: str,
) -> tuple[list[Word], int]:
    filters = _word_filters(
        keyword=keyword,
        tags=tags,
        is_custom=is_custom,
        created_from=created_from,
        created_to=created_to,
    )
    total = db.scalar(select(func.count()).select_from(Word).where(and_(*filters))) or 0
    items = db.scalars(
        select(Word)
        .where(and_(*filters))
        .order_by(*SORTS[sort])
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return list(items), total


def iter_words(
    db: Session,
    *,
    keyword: str | None,
    tags: list[str],
    is_custom: bool | None,
    created_from: str | None,
    created_to: str | None,
    sort: str,
    batch_size: int = 500,
):
    filters = _word_filters(
        keyword=keyword,
        tags=tags,
        is_custom=is_custom,
        created_from=created_from,
        created_to=created_to,
    )
    offset = 0
    while True:
        items = db.scalars(
            select(Word)
            .where(and_(*filters))
            .order_by(*SORTS[sort])
            .offset(offset)
            .limit(batch_size)
        ).all()
        if not items:
            return
        yield from items
        offset += len(items)


def _word_filters(
    *,
    keyword: str | None,
    tags: list[str],
    is_custom: bool | None,
    created_from: str | None,
    created_to: str | None,
):
    filters = [Word.deleted_at.is_(None)]
    if keyword:
        term = f"%{keyword.strip().casefold()}%"
        filters.append(
            or_(
                func.lower(Word.en_word).like(term),
                Word.normalized_en_word.like(term),
                Word.cn_meaning.like(f"%{keyword.strip()}%"),
            )
        )
    if is_custom is not None:
        filters.append(Word.is_custom == int(is_custom))
    if created_from:
        filters.append(Word.created_at >= created_from)
    if created_to:
        filters.append(Word.created_at <= created_to)
    for tag_value in tags:
        _, normalized = normalize_tag(tag_value)
        filters.append(
            Word.id.in_(
                select(WordTag.word_id)
                .join(Tag, Tag.id == WordTag.tag_id)
                .where(Tag.normalized_name == normalized)
            )
        )
    return filters
