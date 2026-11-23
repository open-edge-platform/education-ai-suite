// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Why a setup step most likely failed, read from its error and the setup
// output, so a screen can say what to do instead of only showing the error.
// The first-run installation and the Setup screen both use it.

export type FailureCause = 'certificate' | 'network' | 'disk' | 'backendRunning' | 'filesInUse' | 'other';

const FAILURE_PATTERNS: [FailureCause, RegExp][] = [
  // Before network: a certificate failure also reads "Max retries exceeded".
  ['certificate', /CERTIFICATE_VERIFY_FAILED|SSLCertVerificationError|certificate verify failed|self[- ]signed certificate|unable to get local issuer/i],
  ['disk', /No space left on device|\[Errno 28\]|ERROR_DISK_FULL|not enough space on the disk|0x80070070/i],
  // The setup runner's own refusal, which has a way out: stop the backend.
  ['backendRunning', /Stop the backend first/i],
  ['filesInUse', /used by another process|\[WinError 32\]|\[WinError 5\]|Access is denied/i],
  ['network', /ProxyError|ConnectTimeout|ReadTimeout|Max retries exceeded|NewConnectionError|getaddrinfo failed|Name or service not known|Temporary failure in name resolution|Network is unreachable|Connection (?:refused|reset|aborted)|Could not fetch URL|No matching distribution found|0x80072ee2|0x80072efd|0x80072f8f|Download failed/i],
];

/** What a failed setup step most likely ran into, from its error and output. */
export function classifyFailure(texts: string[]): FailureCause {
  const text = texts.join('\n');
  return FAILURE_PATTERNS.find(([, pattern]) => pattern.test(text))?.[0] ?? 'other';
}

/** Causes the proxy settings can do something about. */
export const isNetworkCause = (cause: FailureCause) => cause === 'network' || cause === 'certificate';
