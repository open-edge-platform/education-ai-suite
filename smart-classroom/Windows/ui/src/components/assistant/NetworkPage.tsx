// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// How the downloads connect: the proxy, a test of what it reaches, and where
// models come from. The same ProxySettings as the Configuration screen. Shown
// when customizing, when the network test failed during the countdown, and to
// fix the network after a failed installation.

import React, { useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useConfig } from '../../services/configManager';
import { useSettingsDraft } from '../../services/settingsDraft';
import { useNow } from '../../hooks/useNow';
import ProblemBanners from '../setup/ProblemBanners';
import ProxySettings from '../setup/ProxySettings';
import { proxyDraft, proxyPrefill, savedProxy } from '../setup/proxyModel';
import { Banner, Button, PageHeader } from '../ui';
import { secondsLeft, type ActiveSnapshot } from './assistantModel';

export type NetworkMode = 'customize' | 'countdown' | 'retry';

interface NetworkPageProps {
  mode: NetworkMode;
  snapshot: ActiveSnapshot;
  onBack?: () => void;
  /** Saved; go on (customize) or install again (retry). */
  onContinue?: () => void;
  /** Install with what there is, now (countdown). */
  onInstallNow?: () => void;
  /** The user acted on the page: stop the countdown. */
  onInterrupt?: () => void;
}

const NetworkPage: React.FC<NetworkPageProps> = ({ mode, snapshot, onBack, onContinue, onInstallNow, onInterrupt }) => {
  const { t } = useTranslation();
  const { description, save, saving, error } = useConfig();
  // The proxy first, then where models come from.
  const fields = useMemo(
    () =>
      (description?.fields.filter((field) => field.onboarding === 'network') ?? []).sort(
        (a, b) => Number(a.file !== 'proxy') - Number(b.file !== 'proxy')
      ),
    [description]
  );
  const { draft, setDraft, changes, blocking, byField, messages, setValue, applyFix, canApply, reset } = useSettingsDraft(
    description,
    fields
  );

  // Start from what the network test found working, so Next saves it. Once,
  // when the saved values are known.
  const prefilled = useRef(false);
  const network = snapshot.network;
  useEffect(() => {
    if (!description || prefilled.current) return;
    prefilled.current = true;
    const saved = savedProxy(description.fields);
    const initial = proxyDraft(proxyPrefill(network, saved), saved);
    const hub = description.fields.find((field) => field.path === 'models.model_hub');
    if (network?.suggestedHub && hub && hub.value !== network.suggestedHub) initial['config:models.model_hub'] = network.suggestedHub;
    if (Object.keys(initial).length) setDraft(initial);
  }, [description, network, setDraft]);

  const counting = snapshot.phase === 'countdown';
  const now = useNow(counting);
  const seconds = secondsLeft(snapshot.endsAt, now);
  const interact = () => {
    if (counting) onInterrupt?.();
  };

  const commit = async () => {
    if (changes.length && !(await save(changes))) return false;
    reset();
    return true;
  };

  return (
    <div className="assistant-page">
      <PageHeader
        focusOnMount
        title={t('assistant.pages.network', 'Network')}
        subtitle={t(
          'assistant.network.lead',
          'Setup downloads Python packages, installers and AI models. Behind a proxy, enter it here; the test shows what each download host answers.'
        )}
      />

      {counting && (
        <Banner tone="warning">
          {t(
            'assistant.network.countdown',
            'Setup could not reach the download hosts. Fix the proxy below, or it tries anyway in {{seconds}} s.',
            { seconds }
          )}
        </Banner>
      )}

      {network?.suggestedHub && (
        <Banner>
          {t('assistant.network.hubSuggested', '{{unreachable}} cannot be reached from here, so models will come from {{source}}.', {
            unreachable: network.hub === 'modelscope' ? 'ModelScope' : 'Hugging Face',
            source: network.suggestedHub === 'modelscope' ? 'ModelScope' : 'Hugging Face',
          })}
        </Banner>
      )}

      {error && <Banner tone="error">{error}</Banner>}
      <ProblemBanners messages={messages} canApply={canApply} onApplyFix={applyFix} />

      {description && (
        <ProxySettings
          description={description}
          fields={fields}
          draft={draft}
          byField={byField}
          onChange={(field, value) => {
            interact();
            setValue(field, value);
          }}
          initialResults={network?.chosen?.results ?? network?.tried?.[0]?.results}
          onInteract={interact}
        />
      )}

      <div className="assistant-actions">
        {mode === 'countdown' && (
          <>
            <Button onClick={interact}>{t('assistant.network.stay', 'Stop the countdown')}</Button>
            <Button variant="primary" onClick={onInstallNow}>
              {t('assistant.network.tryAnyway', 'Try anyway')}
            </Button>
          </>
        )}
        {mode !== 'countdown' && (
          <>
            <Button disabled={saving} onClick={onBack}>
              {t('assistant.back', 'Back')}
            </Button>
            <Button variant="primary" disabled={saving || !description || blocking.length > 0} onClick={async () => (await commit()) && onContinue?.()}>
              {mode === 'retry' ? t('assistant.network.saveRetry', 'Save and retry') : t('assistant.next', 'Next')}
            </Button>
          </>
        )}
      </div>
    </div>
  );
};

export default NetworkPage;
