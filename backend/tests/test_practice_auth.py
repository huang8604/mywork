from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import create_api_client_token
from app.models import ApiClientToken, AuditLog, IdempotencyRecord, ReviewLog, WordStats
from app.schemas import StrategyRequest
from app.services.domain import utc_text
from app.services.strategy import _effective_limits
from conftest import create_word


def test_strategy_defaults_and_total_word_proportions():
    defaults = StrategyRequest()
    assert defaults.new_words_limit == 10
    assert defaults.error_words_limit == 5
    assert defaults.due_words_limit == 5
    assert defaults.custom_words_limit == 5
    assert defaults.total_words is None

    proportional = StrategyRequest(
        new_words_limit=10,
        error_words_limit=5,
        due_words_limit=5,
        custom_words_limit=5,
        total_words=13,
    )
    assert _effective_limits(proportional) == {
        "new": 5,
        "error": 3,
        "due": 3,
        "custom": 2,
    }


def test_total_words_rejects_zero_weights_and_custom_selection(client):
    zero_weights = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-zero-weights"},
        json={
            "new_words_limit": 0,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "total_words": 10,
        },
    )
    assert zero_weights.status_code == 422

    selection = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-selection-with-total"},
        json={
            "word_ids": [1],
            "total_words": 10,
        },
    )
    assert selection.status_code == 422


def test_strategy_boundaries_empty_candidates_limit_and_seed_reproducibility(client):
    empty = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-empty"},
        json={
            "new_words_limit": 10,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "seed": 7,
        },
    )
    assert empty.status_code == 201
    assert empty.json()["data"]["items"] == []
    assert empty.json()["data"]["actual_counts"]["unique_total"] == 0

    over_limit = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-over-limit"},
        json={
            "new_words_limit": 100,
            "error_words_limit": 100,
            "due_words_limit": 1,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
        },
    )
    assert over_limit.status_code == 422
    assert over_limit.json()["code"] == "VALIDATION_ERROR"

    for index in range(6):
        create_word(
            client,
            {"en_word": f"seed-word-{chr(97 + index)}", "cn_meaning": f"释义 {index}", "tags": []},
        )
    payload = {
        "new_words_limit": 4,
        "error_words_limit": 0,
        "due_words_limit": 0,
        "custom_words_limit": 0,
        "fallback_unreviewed_days": 3,
        "seed": 20260720,
    }
    first = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-seed-first"},
        json=payload,
    )
    second = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-seed-second"},
        json=payload,
    )
    assert first.status_code == second.status_code == 201
    assert [item["word_id"] for item in first.json()["data"]["items"]] == [
        item["word_id"] for item in second.json()["data"]["items"]
    ]


def test_strategy_priority_is_error_new_due_custom(client):
    # 新优先级 error→new→due→custom:一个同时属于 new 与 custom 的词,
    # 标签顺序应是 new 在前(旧顺序 error→due→custom→new 会得到 ["custom","new"])。
    custom_word = create_word(
        client, {"en_word": "myword", "cn_meaning": "自造词", "is_custom": True, "tags": []}
    )
    gen = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "gen-priority"},
        json={
            "new_words_limit": 1,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 1,
            "fallback_unreviewed_days": 3,
            "seed": 42,
        },
    )
    assert gen.status_code == 201, gen.text
    data = gen.json()["data"]
    # 该词被"新词"池优先消费(new 优先级高于 custom),source_categories 按新优先级排序。
    assert [item["word_id"] for item in data["items"]] == [custom_word["id"]]
    assert data["items"][0]["source_categories"] == ["new", "custom"]


def test_strategy_backfills_shortfall_from_next_pool(client):
    # 总数 7 按 new:error = 1:2 分为 2:5；错词不足时缺额再顺延到新词池。
    recent = utc_text(datetime.now(UTC) - timedelta(hours=1))  # 近期、不到期、非新词
    for i in range(2):
        w = create_word(
            client, {"en_word": f"err{chr(97 + i)}", "cn_meaning": f"错{i}", "is_custom": False, "tags": []}
        )
        client.post(
            "/api/v1/reviews",
            json={
                "word_id": w["id"],
                "status": "unknown",
                "source": "quick_review",
                "client_event_id": f"err-ev-{i}",
                "reviewed_at": recent,
            },
        )
    for i in range(8):
        create_word(
            client, {"en_word": f"new{chr(97 + i)}", "cn_meaning": f"新{i}", "is_custom": False, "tags": []}
        )
    gen = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "gen-backfill"},
        json={
            "new_words_limit": 1,
            "error_words_limit": 2,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "total_words": 7,
            "fallback_unreviewed_days": 3,
            "seed": 1,
        },
    )
    assert gen.status_code == 201, gen.text
    data = gen.json()["data"]
    # 错词要 5 只有 2 → 缺 3;新词本要 2,补足缺额后挑 5 个 → 总数 7。
    assert data["requested_counts"] == {"new": 2, "error": 5, "due": 0, "custom": 0}
    assert data["actual_counts"]["unique_total"] == 7
    assert data["actual_counts"]["error"] == 2
    assert data["actual_counts"]["new"] == 5


def test_custom_selection_generates_exact_words_in_requested_order(client):
    first = create_word(client, {"en_word": "first", "cn_meaning": "第一", "tags": []})
    second = create_word(client, {"en_word": "second", "cn_meaning": "第二", "tags": []})
    third = create_word(client, {"en_word": "third", "cn_meaning": "第三", "tags": []})
    response = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-custom-selection"},
        json={
            "new_words_limit": 0,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "word_ids": [third["id"], first["id"]],
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert [item["word_id"] for item in data["items"]] == [third["id"], first["id"]]
    assert [item["source_categories"] for item in data["items"]] == [
        ["selected"],
        ["selected"],
    ]
    assert data["requested_counts"] == {"selected": 2}
    assert data["actual_counts"] == {"unique_total": 2, "selected": 2}
    assert second["id"] not in [item["word_id"] for item in data["items"]]

    missing = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-custom-missing"},
        json={
            "new_words_limit": 0,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "word_ids": [999999],
        },
    )
    assert missing.status_code == 422


def test_generate_round_batch_correction_and_replay(client, db_session):
    create_word(client, {"en_word": "warm", "cn_meaning": "温暖", "tags": []})
    create_word(client, {"en_word": "horse", "cn_meaning": "马", "tags": []})
    generated = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-1"},
        json={
            "new_words_limit": 2,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "seed": 123,
        },
    )
    assert generated.status_code == 201, generated.text
    session = generated.json()["data"]
    assert session["actual_counts"]["unique_total"] == 2
    replay = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "generate-1"},
        json={
            "new_words_limit": 2,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "seed": 123,
        },
    )
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["data"]["session_id"] == session["session_id"]

    printed = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/printed",
        headers={"Idempotency-Key": "printed-1"},
    )
    assert printed.status_code == 200
    printed_data = printed.json()["data"]
    assert printed_data["printed_at"] is not None
    printed_replay = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/printed",
        headers={"Idempotency-Key": "printed-1"},
    )
    assert printed_replay.headers["Idempotency-Replayed"] == "true"
    printed_again = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/printed",
        headers={"Idempotency-Key": "printed-2"},
    )
    assert printed_again.json()["data"]["printed_at"] == printed_data["printed_at"]
    assert printed_again.json()["data"]["version"] == printed_data["version"]

    round_response = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/review-rounds",
        headers={"Idempotency-Key": "round-1"},
        json={"mode": "offline", "started_at": "2026-07-20T09:00:00Z"},
    )
    assert round_response.status_code == 201, round_response.text
    round_id = round_response.json()["data"]["round_id"]
    items = session["items"]
    batch = client.put(
        f"/api/v1/practice-review-rounds/{round_id}/results",
        headers={"Idempotency-Key": "batch-1"},
        json={
            "items": [
                {
                    "item_id": items[0]["item_id"],
                    "status": "known",
                    "client_event_id": "batch-event-1",
                },
                {
                    "item_id": items[1]["item_id"],
                    "status": "skipped",
                    "client_event_id": "batch-event-2",
                },
            ]
        },
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["data"]["round"]["status"] == "completed"
    completed_session = client.get(
        f"/api/v1/practice-sessions/{session['session_id']}"
    ).json()["data"]
    assert completed_session["completed_at"] is not None
    assert db_session.scalar(select(func.count()).select_from(ReviewLog)) == 2
    assert db_session.get(WordStats, items[0]["word_id"]).known_count == 1
    assert db_session.get(WordStats, items[1]["word_id"]).skipped_count == 1

    replay_batch = client.put(
        f"/api/v1/practice-review-rounds/{round_id}/results",
        headers={"Idempotency-Key": "batch-1"},
        json={
            "items": [
                {
                    "item_id": items[0]["item_id"],
                    "status": "known",
                    "client_event_id": "batch-event-1",
                },
                {
                    "item_id": items[1]["item_id"],
                    "status": "skipped",
                    "client_event_id": "batch-event-2",
                },
            ]
        },
    )
    assert replay_batch.headers["Idempotency-Replayed"] == "true"
    assert db_session.scalar(select(func.count()).select_from(ReviewLog)) == 2

    round_replay = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/review-rounds",
        headers={"Idempotency-Key": "round-1"},
        json={"mode": "offline", "started_at": "2026-07-20T09:00:00Z"},
    )
    assert round_replay.headers["Idempotency-Replayed"] == "true"
    assert round_replay.json()["data"]["round_id"] == round_id
    next_round = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/review-rounds",
        headers={"Idempotency-Key": "round-2"},
        json={"mode": "offline", "started_at": "2026-07-21T09:00:00Z"},
    )
    assert next_round.status_code == 201
    assert next_round.json()["data"]["round_id"] != round_id


def test_batch_validation_is_atomic(client, db_session):
    create_word(client, {"en_word": "one", "cn_meaning": "一", "tags": []})
    session = client.post(
        "/api/v1/daily-table/generate",
        headers={"Idempotency-Key": "g-atomic"},
        json={
            "new_words_limit": 1,
            "error_words_limit": 0,
            "due_words_limit": 0,
            "custom_words_limit": 0,
            "fallback_unreviewed_days": 3,
            "seed": 1,
        },
    ).json()["data"]
    round_id = client.post(
        f"/api/v1/practice-sessions/{session['session_id']}/review-rounds",
        headers={"Idempotency-Key": "r-atomic"},
        json={"mode": "online"},
    ).json()["data"]["round_id"]
    response = client.put(
        f"/api/v1/practice-review-rounds/{round_id}/results",
        headers={"Idempotency-Key": "b-atomic"},
        json={
            "items": [
                {
                    "item_id": session["items"][0]["item_id"],
                    "status": "known",
                    "client_event_id": "ok",
                },
                {"item_id": 999999, "status": "known", "client_event_id": "bad"},
            ]
        },
    )
    assert response.status_code == 404
    with Session(db_session.get_bind()) as verification:
        assert verification.scalar(select(func.count()).select_from(ReviewLog)) == 0
        assert verification.scalar(select(func.count()).select_from(WordStats)) == 0
        assert verification.scalar(select(func.count()).select_from(IdempotencyRecord)) == 2


def test_bearer_scope_enforcement_and_audit(client, db_session):
    client_record, _token_record, raw = create_api_client_token(
        db_session,
        name="readonly",
        skill_name="test-skill",
        skill_version="1.0",
        scopes=["words:read"],
        expires_days=30,
    )
    denied = client.post(
        "/api/v1/words",
        headers={"Authorization": f"Bearer {raw}"},
        json={"en_word": "denied", "cn_meaning": "拒绝", "tags": []},
    )
    assert denied.status_code == 403
    denied_audit = db_session.scalar(
        select(AuditLog)
        .where(AuditLog.http_status == 403)
        .order_by(AuditLog.id.desc())
    )
    assert denied_audit is not None
    assert denied_audit.outcome == "denied"
    allowed = client.get("/api/v1/words", headers={"Authorization": f"Bearer {raw}"})
    assert allowed.status_code == 200

    token = db_session.scalar(
        select(ApiClientToken).where(ApiClientToken.api_client_id == client_record.id)
    )
    token.revoked_at = utc_text()
    db_session.commit()
    revoked = client.get("/api/v1/words", headers={"Authorization": f"Bearer {raw}"})
    assert revoked.status_code == 401

    create_word(client, {"en_word": "audit", "cn_meaning": "审计", "tags": []})
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) >= 1


def test_capabilities_and_openapi_contract(client):
    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["data"]["review_statuses"] == [
        "known",
        "unknown",
        "skipped",
    ]
    schema = client.get("/openapi.json").json()
    schemes = schema["components"]["securitySchemes"]
    assert "BearerAuth" in schemes
    assert "TrustedProxyUser" in schemes
    operation = schema["paths"]["/api/v1/daily-table/generate"]["post"]
    assert operation["security"] == [{"BearerAuth": []}, {"TrustedProxyUser": []}]
