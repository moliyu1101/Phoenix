"""Attention overview: a read-only projection of everything that needs a person.

The autonomous loop runs, settles and retries on its own. This module surfaces only
the residual decisions a human must make — pending approvals, uncertain side effects,
interrupted runs, unverified answers and dead-lettered effects — so the operator's
panel stays empty while the system is healthy. It never mutates state.
"""
from __future__ import annotations

import json

from .domain import now

SEVERITY_ORDER = {'action': 0, 'review': 1, 'info': 2}


class Attention:
    def __init__(self, components):
        self.c, self.store = components, components.store

    def _item(self, kind: str, severity: str, title: str, detail: str, hint: str,
              refs: dict, created: float) -> dict:
        return {'id': f'{kind}:{refs.get("id", "")}', 'kind': kind, 'severity': severity,
                'title': title, 'detail': detail[:600], 'hint': hint, 'refs': refs, 'created': created}

    def overview(self) -> dict:
        items: list[dict] = []
        items += self._approvals()
        items += self._uncertain_executions()
        items += self._interrupted_runs()
        items += self._awaiting_verification()
        items += self._effects()
        items += self._competition_entries()
        items += self._unknown_submissions()
        items.sort(key=lambda x: (SEVERITY_ORDER.get(x['severity'], 9), -x['created']))
        counts = {'action': 0, 'review': 0, 'info': 0}
        for item in items:
            counts[item['severity']] = counts.get(item['severity'], 0) + 1
        return {'generated': now(), 'total': len(items), 'counts': counts, 'items': items,
                'effect_health': self.c.effects.health() if hasattr(self.c, 'effects') else []}

    def _run_title(self, run_id: str) -> str:
        rows = self.store.all('SELECT c.title FROM runs r JOIN challenges c ON c.id=r.challenge_id WHERE r.id=?',
                              (run_id,))
        return rows[0]['title'] if rows else run_id

    def _approvals(self) -> list[dict]:
        rows = self.store.all("SELECT * FROM request_approvals WHERE state='pending' ORDER BY created LIMIT 100")
        return [self._item('approval', 'action', '待审批的请求', self._run_title(r['run_id']),
                           '审批或拒绝该出站请求', {'id': r['id'], 'run_id': r['run_id']}, r['created']) for r in rows]

    def _uncertain_executions(self) -> list[dict]:
        rows = self.store.all("SELECT run_id,COUNT(*) AS n,MIN(created) AS created FROM executions "
                              "WHERE state='uncertain' GROUP BY run_id LIMIT 100")
        return [self._item('uncertain_execution', 'action', '不确定的沙箱执行',
                           f"{self._run_title(r['run_id'])} · {r['n']} 个执行结果未知",
                           '先 reconcile 沙箱，确认副作用后再恢复', {'id': r['run_id'], 'run_id': r['run_id']},
                           r['created']) for r in rows]

    def _interrupted_runs(self) -> list[dict]:
        rows = self.store.all("SELECT id,reason,updated FROM runs WHERE state='interrupted' ORDER BY updated LIMIT 100")
        return [self._item('interrupted_run', 'action', '中断的运行', self._run_title(r['id']),
                           '确认不确定副作用后显式恢复', {'id': r['id'], 'run_id': r['id']}, r['updated']) for r in rows]

    def _awaiting_verification(self) -> list[dict]:
        rows = self.store.all("SELECT id,updated FROM runs WHERE state='awaiting_verification' ORDER BY updated LIMIT 100")
        return [self._item('awaiting_verification', 'review', '答案待独立验证', self._run_title(r['id']),
                           '提供独立验证或操作者回执，旗标形状字符串不等于已验证',
                           {'id': r['id'], 'run_id': r['id']}, r['updated']) for r in rows]

    def _effects(self) -> list[dict]:
        if not hasattr(self.c, 'effects'):
            return []
        rows = self.store.all("SELECT * FROM effects WHERE state IN ('dead_letter','failed') ORDER BY updated LIMIT 100")
        items = []
        for r in rows:
            payload = json.loads(r['payload'])
            items.append(self._item('effect', 'action', '需人工的副作用',
                                    f"{r['kind']} · {r['last_error'] or r['state']}",
                                    '核对目标系统后重试或丢弃', {'id': r['id'], 'effect_id': r['id'],
                                    'kind': r['kind'], **{k: payload[k] for k in ('entry_id', 'run_id') if k in payload}},
                                    r['updated']))
        return items

    def _competition_entries(self) -> list[dict]:
        rows = self.store.all("SELECT q.*,c.title AS comp_title FROM competition_queue q "
                              "JOIN competitions c ON c.id=q.competition_id WHERE q.state='failed' "
                              'ORDER BY q.updated LIMIT 100')
        return [self._item('competition_entry', 'review', '失败的排队题目',
                           f"{r['comp_title']} · {r['title']}", '查看错误并重新排队或跳过',
                           {'id': r['id'], 'competition_id': r['competition_id'], 'entry_id': r['id']},
                           r['updated']) for r in rows]

    def _unknown_submissions(self) -> list[dict]:
        rows = self.store.all("SELECT q.*,c.title AS comp_title FROM competition_queue q "
                              "JOIN competitions c ON c.id=q.competition_id WHERE q.submission_state='unknown' "
                              'ORDER BY q.updated LIMIT 100')
        return [self._item('submission', 'action', '提交结果未知',
                           f"{r['comp_title']} · {r['title']}", '核对平台回执后重试或丢弃，切勿盲目重提',
                           {'id': r['id'], 'competition_id': r['competition_id'], 'entry_id': r['id'],
                            'submission_id': r['submission_id']}, r['updated']) for r in rows]