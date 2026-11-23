// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// The end of the first run: the backend's first start, which downloads the AI
// models, then what was installed and what still needs doing.

import React from 'react';
import { useTranslation } from 'react-i18next';
import type { ServiceSnapshot } from '../../types/services';
import type { SetupStep } from '../../types/setup';
import { useServiceLogs } from '../../services/serviceManager';
import { formatElapsed, useNow } from '../../hooks/useNow';
import { Banner, Button, PageHeader, Row, RowList } from '../ui';
import { modelDownload, type ActiveSnapshot } from './assistantModel';

interface DonePageProps {
  snapshot: ActiveSnapshot;
  steps: SetupStep[];
  backend: ServiceSnapshot | undefined;
  onStartBackend: () => void;
  onOpenApp: () => void;
  onOpenServices: () => void;
}

const DonePage: React.FC<DonePageProps> = ({ snapshot, steps, backend, onStartBackend, onOpenApp, onOpenServices }) => {
  const { t } = useTranslation();
  const status = backend?.status;
  const starting = status === 'starting';
  const { lines } = useServiceLogs(starting ? 'backend' : null);
  const download = modelDownload(lines.map((line) => line.text));
  const now = useNow(starting, 1000);

  const label = (id: string) => steps.find((step) => step.id === id)?.label ?? id;
  const result = snapshot.result;
  const skipped = result?.manual ?? [];
  const failed = (result?.failed ?? []).filter((entry) => entry.id);

  return (
    <div className="assistant-page">
      <PageHeader
        focusOnMount
        title={
          status === 'healthy'
            ? t('assistant.done.readyTitle', 'Smart Classroom is ready')
            : starting
              ? t('assistant.done.startingTitle', 'Starting Smart Classroom')
              : status === 'failed'
                ? t('assistant.done.failedTitle', 'Smart Classroom did not start')
                : t('assistant.done.installedTitle', 'Smart Classroom is installed')
        }
      />

      {starting && (
        <Banner>
          <div className="assistant-countdown" role="status">
            <span className="ui-spinner" aria-hidden="true" />
            <span>
              {download
                ? t('assistant.done.downloading', 'Downloading {{model}} from {{hub}}', {
                    model: download.repo,
                    hub: download.hub === 'modelscope' ? 'ModelScope' : 'Hugging Face',
                  })
                : t('assistant.done.starting', 'The first start downloads and prepares the AI models, so it takes a while.')}
            </span>
            {backend?.startedAt && <span className="ui-row-meta">{formatElapsed(now - backend.startedAt)}</span>}
          </div>
        </Banner>
      )}

      {status === 'failed' && (
        <Banner tone="error" actions={<Button onClick={onOpenServices}>{t('assistant.done.openServices', 'Open Services')}</Button>}>
          {backend?.error || t('assistant.done.failed', 'The backend stopped while starting. Its log shows why.')}
        </Banner>
      )}

      <RowList label={t('assistant.done.summary', 'Summary')}>
        <Row
          state="ok"
          title={t('assistant.done.installed', 'Installed')}
          detail={
            <span>
              {result?.ran.length ? result.ran.map(label).join(', ') : t('assistant.done.nothingNew', 'Everything was already in place')}
            </span>
          }
        />
        {skipped.length > 0 && (
          <Row
            state="warn"
            title={t('assistant.done.later', 'Still to do')}
            detail={
              <span>
                {t('assistant.done.laterDetail', '{{items}}: fix them on the Setup screen when you are ready.', {
                  items: skipped.map(label).join(', '),
                })}
              </span>
            }
          />
        )}
        {failed.length > 0 && (
          <Row
            state="failed"
            title={t('assistant.done.notInstalled', 'Not installed')}
            detail={<span>{failed.map((entry) => label(entry.id!)).join(', ')}</span>}
          />
        )}
      </RowList>

      <div className="assistant-actions">
        {(status === 'stopped' || status === 'failed') && (
          <Button onClick={onStartBackend}>{t('assistant.done.start', 'Start Smart Classroom')}</Button>
        )}
        <Button variant="primary" disabled={status !== 'healthy'} onClick={onOpenApp}>
          {t('assistant.done.open', 'Open Smart Classroom')}
        </Button>
      </div>
    </div>
  );
};

export default DonePage;
