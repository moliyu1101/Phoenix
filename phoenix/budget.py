from __future__ import annotations

import json

from .config import ModelProfile
from .domain import BudgetExceeded, dump, now, uid
from .store import Store


def upper_token_estimate(messages: list[dict], tools: list[dict] | None = None) -> int:
    """Conservative byte-based admission estimate, not a vendor tokenizer or invoice."""
    return len(dump({'messages': messages, 'tools': tools or []}).encode()) + 256 * (len(messages) + 1)


class Ledger:
    def __init__(self, store: Store):
        self.store = store

    def reserve(self, rid: str, role: str, profile: ModelProfile, input_estimate: int) -> str:
        requested_tokens = input_estimate + profile.output_tokens
        pricing_known = profile.input_usd_per_million is not None and profile.output_usd_per_million is not None
        price = (input_estimate * (profile.input_usd_per_million or 0) +
                 profile.output_tokens * (profile.output_usd_per_million or 0)) / 1_000_000
        call_id = uid('call')
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if row is None:
                raise ValueError('Unknown run')
            limits = json.loads(row['config'])['budget']
            if row['state'] not in ('running', 'distilling'):
                raise BudgetExceeded('Run is not active')
            if now() - row['created'] > limits['wall_seconds']:
                raise BudgetExceeded('Wall-clock budget exhausted')
            if row['calls'] >= limits['max_calls']:
                raise BudgetExceeded('Model call limit exhausted')
            if row['billed_tokens'] + row['held_tokens'] + requested_tokens > limits['max_tokens']:
                raise BudgetExceeded('Token reservation would exceed budget')
            if limits['max_usd'] is not None:
                if not pricing_known:
                    raise BudgetExceeded('USD cap requires input and output prices for every model profile')
                if row['billed_usd'] + row['held_usd'] + price > limits['max_usd']:
                    raise BudgetExceeded('Cost reservation would exceed budget')
            db.execute('UPDATE runs SET calls=calls+1,held_tokens=held_tokens+?,held_usd=held_usd+? WHERE id=?',
                       (requested_tokens, price, rid))
            profile_info = profile.model_dump()
            db.execute('INSERT INTO model_calls(id,run_id,role,profile,status,reserved_tokens,reserved_usd,created) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (call_id, rid, role, dump(profile_info), 'reserved', requested_tokens, price, now()))
        return call_id

    def settle(self, call_id: str, input_tokens: int | None, output_tokens: int | None):
        with self.store.tx() as db:
            row = db.execute('SELECT * FROM model_calls WHERE id=?', (call_id,)).fetchone()
            if not row or row['status'] != 'reserved':
                return
            if input_tokens is None or output_tokens is None or min(input_tokens, output_tokens) < 0:
                # No usage receipt: keep the entire reservation. Never report a free call.
                db.execute("UPDATE model_calls SET status='uncertain',ended=? WHERE id=?", (now(), call_id))
                return
            p = json.loads(row['profile'])
            known = p['input_usd_per_million'] is not None and p['output_usd_per_million'] is not None
            cost = (input_tokens * (p['input_usd_per_million'] or 0) +
                    output_tokens * (p['output_usd_per_million'] or 0)) / 1_000_000
            db.execute('UPDATE runs SET held_tokens=held_tokens-?,held_usd=MAX(0,held_usd-?),'
                       'billed_tokens=billed_tokens+?,billed_usd=billed_usd+? WHERE id=?',
                       (row['reserved_tokens'], row['reserved_usd'], input_tokens + output_tokens,
                        cost, row['run_id']))
            db.execute("UPDATE model_calls SET status='settled',input_tokens=?,output_tokens=?,cost_usd=?,ended=? "
                       'WHERE id=?', (input_tokens, output_tokens, cost if known else None, now(), call_id))

    def uncertain(self, call_id: str):
        self.store.execute("UPDATE model_calls SET status='uncertain',ended=? WHERE id=? AND status='reserved'",
                           (now(), call_id))
