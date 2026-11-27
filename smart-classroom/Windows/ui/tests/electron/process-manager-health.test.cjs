// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// A first start downloads gigabytes of models before the backend answers, so
// a backend that has not answered yet is still starting, however long it
// takes. Degraded is for one that answered and then stopped.

const test = require('node:test');
const assert = require('node:assert/strict');

const { ServiceManager } = require('../../electron/services/process-manager.cjs');
const registry = require('../../electron/services/registry.cjs');

const quietLogs = { setRoute() { }, setTap() { }, note() { }, logFile: () => null, clear() { }, openSink() { }, write() { } };
const HOUR = 60 * 60 * 1000;

function startedLongAgo() {
  const services = new ServiceManager(quietLogs);
  const backend = registry.SERVICES.find((service) => service.id === 'backend');
  services.children.set('backend', { pid: 1234 });
  services.setStatus('backend', 'starting', { startedAt: Date.now() - HOUR, pid: 1234 });
  const check = (healthy) => services.reconcileManaged(backend, new Map([['backend', healthy]]), new Map());
  const status = () => services.snapshot().find((service) => service.id === 'backend').status;
  return { check, status };
}

test('a backend that has not answered yet stays starting while its process lives', () => {
  const { check, status } = startedLongAgo();
  for (let i = 0; i < 10; i++) check(false);
  assert.equal(status(), 'starting');
  check(true);
  assert.equal(status(), 'healthy');
});

test('a backend that answered and then stopped answering is degraded', () => {
  const { check, status } = startedLongAgo();
  check(true);
  check(false);
  check(false);
  assert.equal(status(), 'healthy');
  check(false);
  assert.equal(status(), 'degraded');
});
