// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// Features chosen by group, each group expandable into its individual
// toggles: the same in the setup assistant and on the Configuration screen.

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import '../../assets/css/SettingsSections.css';
import type { ConfigDescription, ConfigField, ConfigProblem, ConfigValue } from '../../types/config';
import { fieldKey } from '../../services/configManager';
import type { Draft } from '../../services/settingsDraft';
import { Button } from '../ui';
import { groupFields, groupOfField, groupState } from './featureModel';
import SettingsFields from './SettingsFields';

interface FeaturePickerProps {
  description: ConfigDescription;
  draft: Draft;
  byField: Map<string, ConfigProblem>;
  onChange: (field: ConfigField, value: ConfigValue) => void;
  /** Also show each group's own settings (fields placed in it), as the assistant does. */
  withSettings?: boolean;
  flashedKey?: string | null;
  idPrefix?: string;
}

const FeaturePicker: React.FC<FeaturePickerProps> = ({
  description,
  draft,
  byField,
  onChange,
  withSettings = false,
  flashedKey,
  idPrefix,
}) => {
  const { t } = useTranslation();
  const fields = description.fields;
  const [open, setOpen] = useState<Record<string, boolean>>({});

  // Sent here to one field (a problem's "Show setting"): open its group.
  useEffect(() => {
    if (!flashedKey) return;
    const group = groupOfField(description.featureGroups, fields, fieldKey, flashedKey);
    if (group) setOpen((previous) => ({ ...previous, [group.id]: true }));
  }, [flashedKey, description, fields]);

  const isOn = (field: ConfigField) => (draft[fieldKey(field)] ?? field.value) !== false;

  return (
    <div className="feature-picker">
      {description.featureGroups.map((group) => {
        const members = groupFields(group, fields);
        const state = groupState(members, isOn);
        const settings = withSettings ? fields.filter((field) => field.onboarding === group.id) : [];
        const expanded = !!open[group.id];
        const title = t(`featureGroups.${group.id}.title`, group.label);
        return (
          <div key={group.id} className={`feature-group ${state}`}>
            <div className="feature-group-head">
              <input
                id={`feature-group-${group.id}`}
                type="checkbox"
                checked={state === 'on'}
                ref={(input) => {
                  if (input) input.indeterminate = state === 'mixed';
                }}
                onChange={(event) => members.forEach((field) => onChange(field, event.target.checked))}
              />
              <label htmlFor={`feature-group-${group.id}`} className="feature-group-text">
                <span className="feature-group-title">{title}</span>
                <span className="feature-group-detail">{t(`featureGroups.${group.id}.detail`, group.detail)}</span>
                {state === 'mixed' && (
                  <span className="feature-group-count">
                    {t('featureGroups.count', '{{on}} of {{total}} on', {
                      on: members.filter(isOn).length,
                      total: members.length,
                    })}
                  </span>
                )}
              </label>
              <Button
                variant="link"
                aria-expanded={expanded}
                aria-controls={`feature-group-body-${group.id}`}
                onClick={() => setOpen((previous) => ({ ...previous, [group.id]: !expanded }))}
              >
                {expanded ? t('featureGroups.hide', 'Hide details') : t('featureGroups.show', 'Details')}
              </Button>
            </div>
            {expanded && (
              <div id={`feature-group-body-${group.id}`} className="feature-group-body">
                <SettingsFields
                  fields={members}
                  allFields={fields}
                  draft={draft}
                  byField={byField}
                  onChange={onChange}
                  flashedKey={flashedKey}
                  idPrefix={idPrefix}
                />
                {settings.length > 0 && (
                  <SettingsFields
                    fields={settings}
                    allFields={fields}
                    draft={draft}
                    byField={byField}
                    onChange={onChange}
                    flashedKey={flashedKey}
                    idPrefix={idPrefix}
                  />
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default FeaturePicker;
