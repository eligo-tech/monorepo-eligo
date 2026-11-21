"""ELI-69: "Angelegt von" for rows created before the column — only where proven.

`managers.created_by_*` exists since 0085, `companies.created_by_*` since
0086. Rows older than that have no creator. This fills it ONLY where a
creation receipt in the SAME workspace names the row and carries an actor
(`receipts.actor_user_id`, from the logged-in account). Nothing is inferred
from a name, an e-mail or a timestamp alone; a row without such a receipt
stays NULL, and the UI says "unbekannt".

    # what would be filled (writes nothing)
    .venv/bin/python -m scripts.backfill_created_by

    # do it
    .venv/bin/python -m scripts.backfill_created_by --apply

## The proofs, all of them

1. A lead entered by hand (ELI-65): `create_manual_lead` writes ONE receipt,
   `agent="recruiter"`, `subject_type="manager"`, summary
   "Lead von Hand angelegt", for the row it creates → that lead's creator,
   when the receipt carries the account id. Until ELI-69 that receipt named
   the actor's display NAME only (`actor_user_id` NULL): a name is not an
   account, so those leads are left alone.
2. A company adopted from Markt: `hub.service.adopt_company` creates the
   company and writes `agent="recruiter_adopt_company"`, `WRITE`,
   `subject_type="company"` for it → that company's creator.
3. The company a hand-entered lead created: the lead's receipt names
   `payload.company_id` (which must also be the lead's `company_id`), and
   that company was created in the SAME transaction exactly when its
   `created_at` equals the lead's: both come from `TimestampMixin`'s
   `default=func.now()`, the DATABASE's transaction start time on Postgres —
   not a Python-side clock. A company that existed before carries an earlier
   `created_at` and is left alone. The account is the receipt's, else the
   lead's own `created_by_*` — stamped by `CreatedByMixin` (since 0085) in
   that same request, so it is the same person.

Not proofs, and so not used: an edit receipt (it says who changed a row, not
who made it); a receipt without an actor; a receipt of another workspace.

## Re-running it

Only NULL creators are written, so a second run fills nothing. `updated_at`
is kept as it was: attributing a row is not editing it.

Why a script and not the migration: `receipts.subject_id` is TEXT while the
ids are uuid on Postgres and 32 hex chars on SQLite, and proof 3 reads the
receipt's JSON payload — no single SQL statement is portable across both.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import select, update

from app.core.database import AdminSessionLocal

# Every table on the metadata: `managers.company_id` and friends are foreign
# keys resolved at mapper configuration.
from app.domain import registry  # noqa: F401
from app.domain.common.enums import ReceiptAction
from app.domain.companies.models import Company
from app.domain.managers.models import Manager
from app.domain.verification.models import Receipt

MANUAL_LEAD = {"agent": "recruiter", "subject_type": "manager", "summary": "Lead von Hand angelegt"}
ADOPTED_COMPANY = {"agent": "recruiter_adopt_company", "subject_type": "company"}


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _receipts(session, *, with_account: bool, **match) -> list[Receipt]:
    """Creation receipts, oldest first (the first one wins)."""
    stmt = select(Receipt).where(
        Receipt.action == ReceiptAction.WRITE.value,
        *((Receipt.actor_user_id.is_not(None),) if with_account else ()),
        *(getattr(Receipt, k) == v for k, v in match.items()),
    )
    return list((await session.scalars(stmt.order_by(Receipt.tenant_id, Receipt.chain_index))).all())


async def _fill(
    session, model, row_id: uuid.UUID, tenant_id: uuid.UUID, account: tuple[str, str | None], apply: bool
) -> bool:
    """Attribute one row of the receipt's workspace, if it has no creator yet."""
    row = await session.scalar(
        select(model).where(
            model.id == row_id,
            model.tenant_id == tenant_id,
            model.created_by_user_id.is_(None),
        )
    )
    if row is None:
        return False
    if apply:
        await session.execute(
            update(model)
            .where(model.id == row.id, model.tenant_id == tenant_id, model.created_by_user_id.is_(None))
            .values(
                created_by_user_id=account[0],
                created_by_name=account[1],
                # An explicit value: `onupdate` would otherwise stamp now.
                updated_at=model.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
    return True


async def run(*, apply: bool) -> dict[str, int]:
    """Fill what the receipts prove; return how many rows per table."""
    filled = {"managers": 0, "companies": 0}
    seen: set[tuple[str, uuid.UUID]] = set()
    async with AdminSessionLocal() as session:
        for receipt in await _receipts(session, with_account=False, **MANUAL_LEAD):
            manager_id = _uuid(receipt.subject_id)
            if manager_id is None or ("m", manager_id) in seen:
                continue
            seen.add(("m", manager_id))
            lead = await session.scalar(
                select(Manager).where(Manager.id == manager_id, Manager.tenant_id == receipt.tenant_id)
            )
            if lead is None:
                continue
            # Proof 1: only a receipt that names the account.
            account = (receipt.actor_user_id, receipt.actor_name) if receipt.actor_user_id else None
            if account and await _fill(session, Manager, manager_id, receipt.tenant_id, account, apply):
                filled["managers"] += 1
            # Proof 3: the company this lead created in the same transaction,
            # by the receipt's account or the one the request stamped on the lead.
            account = account or (
                (lead.created_by_user_id, lead.created_by_name) if lead.created_by_user_id else None
            )
            company_id = _uuid((receipt.payload or {}).get("company_id"))
            if account is None or company_id is None or company_id != lead.company_id or ("c", company_id) in seen:
                continue
            company = await session.scalar(
                select(Company).where(Company.id == company_id, Company.tenant_id == receipt.tenant_id)
            )
            if company is not None and company.created_at == lead.created_at:
                seen.add(("c", company_id))
                if await _fill(session, Company, company_id, receipt.tenant_id, account, apply):
                    filled["companies"] += 1

        for receipt in await _receipts(session, with_account=True, **ADOPTED_COMPANY):
            company_id = _uuid(receipt.subject_id)
            if company_id is None or ("c", company_id) in seen:
                continue
            seen.add(("c", company_id))
            account = (receipt.actor_user_id, receipt.actor_name)
            if await _fill(session, Company, company_id, receipt.tenant_id, account, apply):
                filled["companies"] += 1

        if apply:
            await session.commit()
        else:
            await session.rollback()
    return filled


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    filled = asyncio.run(run(apply=apply))
    verb = "filled" if apply else "would fill (dry run; --apply to write)"
    print(f"{verb}: {filled['managers']} leads/managers, {filled['companies']} companies")


if __name__ == "__main__":
    main()
