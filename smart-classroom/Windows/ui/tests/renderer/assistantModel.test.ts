// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import {
  adminTasks,
  awaitingApproval,
  installSteps,
  itemStatus,
  modelDownload,
  onboardingPage,
  pageOrder,
  railItems,
  secondsLeft,
  stepCounter,
  type ActiveSnapshot,
} from '../../src/components/assistant/assistantModel';
import { formatElapsed } from '../../src/hooks/useNow';
import type { SetupStep } from '../../src/types/setup';

const snapshot = (patch: Partial<ActiveSnapshot> = {}): ActiveSnapshot => ({
  active: true,
  phase: 'checking',
  held: null,
  caution: null,
  endsAt: null,
  diskLow: false,
  recommended: false,
  includeElevated: false,
  network: null,
  plan: null,
  result: null,
  record: null,
  ...patch,
});

const step = (id: string, status: SetupStep['status'], repairKind: SetupStep['repairKind'] = null): SetupStep =>
  ({ id, label: id, status, repairKind, section: 'software', optional: false, requires: [], actions: [], detail: '', detailKey: null, detailParams: {}, repair: null, hint: null }) as SetupStep;

const finished = (envOk: boolean) => ({ ran: [], failed: [], blocked: [], manual: [], envOk });

describe('pages', () => {
  it('orders the pages, with administrator tasks only when needed', () => {
    expect(pageOrder(false)).toEqual(['welcome', 'network', 'features', 'install', 'done']);
    expect(pageOrder(true)).toEqual(['welcome', 'network', 'features', 'admin', 'install', 'done']);
  });

  it('follows the first-run flow', () => {
    expect(onboardingPage(null, null)).toBeNull();
    expect(onboardingPage(snapshot({ phase: 'manual' }), null)).toBeNull();
    expect(onboardingPage(snapshot({ phase: 'checking' }), null)).toBe('welcome');
    expect(onboardingPage(snapshot({ phase: 'countdown', caution: 'network' }), null)).toBe('network');
    expect(onboardingPage(snapshot({ phase: 'countdown', caution: 'disk' }), null)).toBe('welcome');
    expect(onboardingPage(snapshot({ phase: 'installing' }), 'network')).toBe('install');
    expect(onboardingPage(snapshot({ phase: 'finished', result: finished(true) }), 'network')).toBe('done');
  });

  it('lets a customizing user move through the pages, even before the checks finish', () => {
    expect(onboardingPage(snapshot({ phase: 'checking', held: 'customize' }), null)).toBe('network');
    expect(onboardingPage(snapshot({ phase: 'waiting', held: 'customize' }), 'features')).toBe('features');
    expect(onboardingPage(snapshot({ phase: 'waiting', held: 'customize' }), 'done')).toBe('network');
    expect(onboardingPage(snapshot({ phase: 'waiting', held: 'choice' }), 'features')).toBe('welcome');
  });

  it('sends a failed or stopped installation to the network page on request', () => {
    expect(onboardingPage(snapshot({ phase: 'finished', result: finished(false) }), null)).toBe('install');
    expect(onboardingPage(snapshot({ phase: 'finished', result: finished(false) }), 'network')).toBe('network');
    expect(onboardingPage(snapshot({ phase: 'waiting', held: 'cancelled' }), 'network')).toBe('network');
  });

  it('shows progress on the rail', () => {
    const rail = railItems(pageOrder(false), 'features');
    expect(rail.map((item) => item.state)).toEqual(['complete', 'complete', 'current', 'upcoming', 'upcoming']);
  });
});

describe('time', () => {
  it('formats elapsed time and counts down whole seconds', () => {
    expect(formatElapsed(65_000)).toBe('1:05');
    expect(formatElapsed(3_725_000)).toBe('1:02:05');
    expect(secondsLeft(10_000, 9_001)).toBe(1);
    expect(secondsLeft(10_000, 20_000)).toBe(0);
    expect(secondsLeft(null, 0)).toBe(0);
  });
});

describe('installation', () => {
  const plan = [
    { stepId: 'longPaths', actionId: 'enable', kind: 'elevated' as const },
    { stepId: 'python', actionId: 'install', kind: 'auto' as const },
    { stepId: 'venv', actionId: 'create', kind: 'auto' as const },
    { stepId: 'old', actionId: 'recreate', kind: 'manual' as const },
  ];
  const steps = [step('longPaths', 'missing', 'elevated'), step('python', 'ok'), step('venv', 'running', 'auto')];

  it('runs the queue in order, keeping unapproved elevated steps for the approval card', () => {
    expect(installSteps(plan, steps, false).map((entry) => entry.id)).toEqual(['python', 'venv']);
    expect(installSteps(plan, steps, true).map((entry) => entry.id)).toEqual(['longPaths', 'python', 'venv']);
    expect(awaitingApproval(snapshot({ plan }), steps).map((entry) => entry.id)).toEqual(['longPaths']);
    expect(awaitingApproval(snapshot({ plan, includeElevated: true }), steps)).toEqual([]);
  });

  it('reads each step\'s place, and a step still missing after the run as not done', () => {
    expect(itemStatus(step('a', 'running'), false)).toBe('running');
    expect(itemStatus(step('a', 'warn'), false)).toBe('done');
    expect(itemStatus(step('a', 'missing'), false)).toBe('pending');
    expect(itemStatus(step('a', 'missing'), true)).toBe('failed');
  });

  it('counts steps, the first start included', () => {
    expect(stepCounter(['done', 'running'], 1)).toEqual({ step: 2, total: 3 });
    expect(stepCounter(['done'], 1)).toEqual({ step: 2, total: 2 });
  });

  it('finds the administrator tasks from the setup data', () => {
    expect(adminTasks([step('x', 'missing', 'elevated'), step('y', 'missing', 'auto'), step('z', 'ok', 'elevated')]).map((entry) => entry.id)).toEqual(['x']);
  });
});

describe('downloads', () => {
  it('reads the model being downloaded from the backend log', () => {
    const lines = [
      '[INFO] utils.model_download_helper: Downloading openai/whisper-small@default from Hugging Face -> C:\\models',
      '[INFO] utils.model_download_helper: Downloading Qwen/Qwen3.5-9B@main from ModelScope -> C:\\models',
    ];
    expect(modelDownload(lines)).toEqual({ repo: 'Qwen/Qwen3.5-9B', hub: 'modelscope' });
    expect(modelDownload(['nothing'])).toBeNull();
  });
});
