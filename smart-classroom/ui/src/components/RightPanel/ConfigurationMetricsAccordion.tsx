import React, { useEffect, useRef, useState } from "react";
import Accordion from "../common/Accordion";
import "../../assets/css/RightPanel.css"; 
import { useTranslation } from 'react-i18next';
import { getSettings } from '../../services/api';

const ConfigurationMetricsAccordion: React.FC = () => {
  const { t } = useTranslation();
  const [configData] = useState<any>(null);
  const didRunRef = useRef(false); // guard StrictMode double-invoke

  useEffect(() => {
    if (didRunRef.current) return;
    didRunRef.current = true;

    (async () => {
      try {
        // Ensure first call is /project
        await getSettings();
// -        const data = await getConfigurationMetrics();
// -        setConfigData(data);
//+        // Defer calling /configuration-metrics; it will be triggered later in the flow
      } catch {
        // ignore (keep placeholder UI)
      }
    })();
  }, []);

  return (
    <Accordion title={t('accordion.configuration')}>
      <div className="accordion-subtitle">{t('accordion.subtitle_configuration')}</div>
      {configData ? (
        <div className="configuration-metrics">
          <div className="platform-configuration">
            <h3>{t('accordion.platformConfiguration') || "Platform Configuration"}</h3>
            <p>{t('accordion.processor') || "Processor"}: {configData.platform_configuration.processor}</p>
            <p>{t('accordion.npu') || "NPU"}: {configData.platform_configuration.npu}</p>
            <p>{t('accordion.igpu') || "iGPU"}: {configData.platform_configuration.igpu}</p>
            <p>{t('accordion.memory') || "Memory"}: {configData.platform_configuration.memory}</p>
            <p>{t('accordion.storage') || "Storage"}: {configData.platform_configuration.storage}</p>
          </div>
          <div className="software-performance">
            <h3>{t('accordion.softwareConfiguration') || "Software Configuration"}</h3>
            <p>{t('accordion.llm') || "LLM"}: {configData.software_configuration.llm}</p>
            <p>{t('accordion.asr') || "ASR"}: {configData.software_configuration.asr}</p>
            <h3>{t('accordion.performanceMetrics') || "Performance Metrics"}</h3>
            <p>{t('accordion.ttft') || "TTFT"}: {configData.performance_metrics.ttft}</p>
            <p>{t('accordion.tpot') || "TPOT"}: {configData.performance_metrics.tpot}</p>
            <p>{t('accordion.totalTokensProcessed') || "Total tokens processed"}: {configData.performance_metrics.total_tokens_processed}</p>
            <p>{t('accordion.timeToGenerateSummary') || "Time taken to generate summary"}: {configData.performance_metrics.time_to_generate_summary}</p>
          </div>
        </div>
      ) : (
        <p className="accordion-content">{t('accordion.loadingConfiguration') || "Loading configuration data..."}</p>
      )}
    </Accordion>
  );
};

export default ConfigurationMetricsAccordion;