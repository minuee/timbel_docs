"""Webhook 이벤트 디스패처 — 등록된 Webhook으로 이벤트 비동기 발행.

Phase 2 강화:
- 지수 백오프 재시도 (2s, 4s, 8s, 16s — 최대 5회)
- Dead Letter Queue (실패 이벤트 DB 저장, 수동 재시도 가능)
- HMAC-SHA256 서명 (모든 아웃바운드 Webhook에 적용)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.logging import get_logger
from src.integration.metrics import WEBHOOK_DISPATCHES_TOTAL
from src.integration.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from src.integration.webhook.models import (
    WebhookConfigORM,
    WebhookDeadLetterORM,
    WebhookEvent,
)

log = get_logger(__name__)


class WebhookDispatcher:
    """Webhook 이벤트 디스패처.

    등록된 Webhook 중 해당 이벤트를 구독하는 대상에 HTTP POST를 보낸다.
    HMAC-SHA256 서명으로 페이로드 무결성을 보장한다.
    실패 시 5회 지수 백오프 재시도(2s, 4s, 8s, 16s)를 수행한다.
    최종 실패 시 Dead Letter Queue에 저장한다.
    """

    MAX_RETRIES = 5
    BASE_BACKOFF_SECONDS = 2  # 2, 4, 8, 16초
    TIMEOUT_SECONDS = 10

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._circuit_breaker = CircuitBreaker(
            name="webhook_dispatch",
            failure_threshold=5,
            recovery_timeout=30.0,
            half_open_max_calls=3,
        )

    async def dispatch(
        self,
        event_type: str,
        tenant_id: UUID,
        payload: dict,
    ) -> int:
        """이벤트를 구독 중인 모든 Webhook에 발행.

        Args:
            event_type: 이벤트 타입 (예: "document.indexed")
            tenant_id: 테넌트 ID
            payload: 이벤트 페이로드

        Returns:
            성공적으로 발행된 Webhook 수.
        """
        webhooks = await self._get_subscribed_webhooks(event_type, tenant_id)
        if not webhooks:
            log.info("webhook_no_subscribers", event_type=event_type)
            return 0

        event = WebhookEvent(
            event_id=uuid4(),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            payload=payload,
        )
        event_body = event.model_dump_json()

        log.info(
            "webhook_dispatch_start",
            event_type=event_type,
            event_id=str(event.event_id),
            subscriber_count=len(webhooks),
        )

        # 병렬 발행 (circuit breaker 적용)
        tasks = [
            self._send_with_circuit_breaker(wh, event_type, event_body, event.event_id)
            for wh in webhooks
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if r is True)
        log.info(
            "webhook_dispatch_complete",
            event_type=event_type,
            event_id=str(event.event_id),
            success=success_count,
            total=len(webhooks),
        )

        return success_count

    async def retry_dead_letter(self, dead_letter_id: UUID) -> bool:
        """Dead Letter Queue의 실패 이벤트를 수동 재시도.

        Args:
            dead_letter_id: Dead Letter 레코드 ID

        Returns:
            재시도 성공 여부.
        """
        dl = await self._session.get(WebhookDeadLetterORM, dead_letter_id)
        if not dl:
            log.warning("dead_letter_not_found", id=str(dead_letter_id))
            return False

        webhook = await self._session.get(WebhookConfigORM, dl.webhook_id)
        if not webhook or not webhook.is_active:
            log.warning("webhook_inactive_for_retry", webhook_id=str(dl.webhook_id))
            return False

        success = await self._send_single(
            webhook=webhook,
            event_type=dl.event_type,
            body=dl.event_body,
        )

        if success:
            # DLQ 레코드 삭제
            await self._session.delete(dl)
            log.info("dead_letter_retry_success", id=str(dead_letter_id))
        else:
            # 재시도 횟수 증가
            dl.retry_count += 1
            dl.last_retry_at = datetime.now(timezone.utc)
            log.warning("dead_letter_retry_failed", id=str(dead_letter_id))

        return success

    async def _send_with_circuit_breaker(
        self,
        webhook: WebhookConfigORM,
        event_type: str,
        body: str,
        event_id: UUID,
    ) -> bool:
        """Circuit breaker를 통해 Webhook 전송을 실행한다."""
        try:
            result = await self._circuit_breaker.call(
                self._send_with_retry, webhook, event_type, body, event_id
            )
            WEBHOOK_DISPATCHES_TOTAL.labels(event=event_type, status="success").inc()
            return result
        except CircuitBreakerOpen:
            WEBHOOK_DISPATCHES_TOTAL.labels(event=event_type, status="circuit_open").inc()
            log.warning(
                "webhook_circuit_breaker_open",
                webhook_id=str(webhook.id),
                event_type=event_type,
            )
            # Circuit open 시 DLQ에 저장
            await self._store_dead_letter(
                webhook_id=webhook.id,
                event_type=event_type,
                event_body=body,
                event_id=event_id,
                last_error="Circuit breaker OPEN — 전송 차단됨",
            )
            return False
        except Exception:
            WEBHOOK_DISPATCHES_TOTAL.labels(event=event_type, status="failure").inc()
            return False

    async def _send_with_retry(
        self,
        webhook: WebhookConfigORM,
        event_type: str,
        body: str,
        event_id: UUID,
    ) -> bool:
        """단일 Webhook에 이벤트 전송. 실패 시 지수 백오프 재시도."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            success = await self._send_single(webhook, event_type, body)
            if success:
                await self._mark_success(webhook.id)
                log.info(
                    "webhook_sent",
                    webhook_id=str(webhook.id),
                    url=webhook.url[:80],
                    attempt=attempt,
                )
                return True

            # 재시도 대기 (지수 백오프: 2, 4, 8, 16초)
            if attempt < self.MAX_RETRIES:
                wait = self.BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                log.info(
                    "webhook_retry_wait",
                    webhook_id=str(webhook.id),
                    attempt=attempt,
                    wait_seconds=wait,
                )
                await asyncio.sleep(wait)

        # 최종 실패 — failure_count 증가 + DLQ 저장
        await self._mark_failure(webhook.id)
        await self._store_dead_letter(
            webhook_id=webhook.id,
            event_type=event_type,
            event_body=body,
            event_id=event_id,
            last_error=f"전송 실패: {self.MAX_RETRIES}회 재시도 후 최종 실패",
        )
        log.error(
            "webhook_delivery_failed_to_dlq",
            webhook_id=str(webhook.id),
            url=webhook.url[:80],
            event_id=str(event_id),
            max_retries=self.MAX_RETRIES,
        )
        return False

    async def _send_single(
        self,
        webhook: WebhookConfigORM,
        event_type: str,
        body: str,
    ) -> bool:
        """단일 전송 시도. HMAC-SHA256 서명 포함."""
        signature = hmac.new(
            webhook.secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-AICM-Signature": f"sha256={signature}",
            "X-AICM-Event": event_type,
            "User-Agent": "AICM-Webhook/2.0",
        }

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    webhook.url,
                    content=body,
                    headers=headers,
                )
            if 200 <= response.status_code < 300:
                return True

            log.warning(
                "webhook_non_2xx",
                webhook_id=str(webhook.id),
                status=response.status_code,
            )
            return False

        except Exception as e:
            log.warning(
                "webhook_send_error",
                webhook_id=str(webhook.id),
                error=str(e),
            )
            return False

    async def _get_subscribed_webhooks(
        self,
        event_type: str,
        tenant_id: UUID,
    ) -> list[WebhookConfigORM]:
        """해당 이벤트를 구독하는 활성 Webhook 목록 조회."""
        stmt = (
            select(WebhookConfigORM)
            .where(
                WebhookConfigORM.tenant_id == tenant_id,
                WebhookConfigORM.is_active.is_(True),
                WebhookConfigORM.events.any(event_type),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _mark_success(self, webhook_id: UUID) -> None:
        """Webhook 전송 성공 기록."""
        stmt = (
            update(WebhookConfigORM)
            .where(WebhookConfigORM.id == webhook_id)
            .values(last_triggered_at=datetime.now(timezone.utc))
        )
        await self._session.execute(stmt)

    async def _mark_failure(self, webhook_id: UUID) -> None:
        """Webhook 전송 실패 기록."""
        stmt = (
            update(WebhookConfigORM)
            .where(WebhookConfigORM.id == webhook_id)
            .values(failure_count=WebhookConfigORM.failure_count + 1)
        )
        await self._session.execute(stmt)

    async def _store_dead_letter(
        self,
        webhook_id: UUID,
        event_type: str,
        event_body: str,
        event_id: UUID,
        last_error: str,
    ) -> None:
        """실패 이벤트를 Dead Letter Queue에 저장."""
        dl = WebhookDeadLetterORM(
            webhook_id=webhook_id,
            event_id=event_id,
            event_type=event_type,
            event_body=event_body,
            last_error=last_error,
        )
        self._session.add(dl)
        log.info(
            "webhook_dead_letter_stored",
            webhook_id=str(webhook_id),
            event_id=str(event_id),
            event_type=event_type,
        )
