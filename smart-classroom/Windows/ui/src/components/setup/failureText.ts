// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import type { FailureCause } from '../../services/setupFailure';

/** What to tell the user about a failed setup step, by cause. */
export function useFailureText() {
  const { t } = useTranslation();
  return useCallback(
    (cause: FailureCause) => {
      switch (cause) {
        case 'network':
          return t('assistant.install.causes.network', 'A download failed. Check the network settings, then retry.');
        case 'certificate':
          return t(
            'assistant.install.causes.certificate',
            'A download was refused because the connection is inspected and its certificate is not trusted. Ask your IT department, or try another network.'
          );
        case 'disk':
          return t('assistant.install.causes.disk', 'The disk is full. Free some space, then retry.');
        case 'backendRunning':
          return t(
            'assistant.install.causes.backendRunning',
            'The backend is using files this step replaces. Stop it on the Services screen, then retry.'
          );
        case 'filesInUse':
          return t(
            'assistant.install.causes.filesInUse',
            'Files that setup has to replace are in use. Close other Smart Classroom windows, then retry.'
          );
        default:
          return t('assistant.install.causes.other', 'A step failed. The details below show what it reported.');
      }
    },
    [t]
  );
}
