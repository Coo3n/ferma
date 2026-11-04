"""A08: a queued timeout must not turn into a delayed physical action."""
import queue
import subprocess
from concurrent.futures import Future
from pathlib import Path

import pytest

from _node import require_node
from farm.api import bulk


def test_timeout_cancels_pending_action_before_worker_executes(monkeypatch):
    monkeypatch.setattr(bulk, "QUEUED_WAIT", 0)
    monkeypatch.setattr(bulk, "_sleeping", {})
    pending = Future()
    result = bulk._wait_queued({"PHONE": pending}, 0)["PHONE"]
    calls = []
    q = queue.Queue()
    q.put((0, lambda s: calls.append(s), pending))
    # Run the real worker until this finite test queue is empty.
    get = q.get
    monkeypatch.setattr(q, "get", lambda: get(block=False))
    with pytest.raises(queue.Empty):
        bulk._worker("PHONE", q)
    assert calls == []
    assert pending.cancelled()
    assert not result["ok"] and result["retryable"] is True


def test_running_timeout_is_unknown_not_retryable(monkeypatch):
    monkeypatch.setattr(bulk, "QUEUED_WAIT", 0)
    running = Future()
    assert running.set_running_or_notify_cancel()
    result = bulk._wait_queued({"PHONE": running}, 0)["PHONE"]
    assert result["ok"] is False
    assert result["reason"] == "outcome_unknown"
    assert result["retryable"] is False
    assert not running.cancelled()
    running.set_result(None)


def test_finished_action_keeps_success(monkeypatch):
    monkeypatch.setattr(bulk, "QUEUED_WAIT", 0)
    done = Future()
    done.set_result({"value": 7})
    assert bulk._wait_queued({"PHONE": done}, 0) == {"PHONE": {"ok": True, "value": 7}}


def test_ui_retry_excludes_unknown_outcomes():
    js = Path(__file__).resolve().parents[2] / "frontend/js/bulk.js"
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const box = {dataset: {}, innerHTML: '', scrollIntoView() {}, querySelector() {return null;}};
const modal = {classList: {contains: () => true}};
const ctx = {window: {}, store: {get: (k, d) => d},
  document: {addEventListener() {}, querySelectorAll: () => []},
  S: {devices: [{serial:'pending'}, {serial:'unknown'}, {serial:'offline'}]},
  $: id => id === 'modal' ? modal : box, esc: String, deviceLabel: String,
  t: (k, p) => k === 'bulk.povtorit' ? 'retry-'+p.n : k, toast() {},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
ctx.window.BULK_RUN.last = {what: 'tap', serials: ['pending','unknown','offline'], res: {results: {
  pending: {ok:false, reason:'timeout_cancelled', retryable:true},
  unknown: {ok:false, reason:'outcome_unknown', retryable:false, error:'Результат неизвестен'},
  offline: {ok:false, reason:'offline'},
}}};
vm.runInContext('bulkPaint()', ctx);
assert.ok(box.innerHTML.includes('retry-2'));
assert.ok(box.innerHTML.includes('Результат неизвестен'));
vm.runInContext('bulkRun = (what, serials) => { this.retried = serials; }; bulkRetry()', ctx);
assert.deepStrictEqual(Array.from(ctx.retried), ['pending','offline']);
ctx.window.BULK_RUN.last.res.results = {unknown: {ok:false, retryable:false, error:'Результат неизвестен'}};
vm.runInContext('bulkPaint()', ctx);
assert.ok(!box.innerHTML.includes('onclick="bulkRetry()"'));
"""
    out = subprocess.run([require_node(), "-e", script, str(js)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
