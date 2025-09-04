import React from "react";
import Accordion from "../common/Accordion";
import "../../assets/css/RightPanel.css"; 
import { useTranslation } from "react-i18next";

const PreValidatedModelsAccordion: React.FC = () => {
  const { t } = useTranslation();
  return (
    <Accordion title={t('accordion.models')}>
      <div className="accordion-subtitle">{t('accordion.subtitle_models')}</div>
      <div className="dropdown-container">
        <div className="dropdown-section">
          <div className="accordion-content">{t('accordion.transcriptsModel')}</div>
          <select className="dropdown">
            <option value="whisper">{t('accordion.whisper')}</option>
            <option value="model1">{t('accordion.model1')}</option>
            <option value="model2">{t('accordion.model2')}</option>
          </select>
        </div>
        <div className="dropdown-section">
          <div className="accordion-content">{t('accordion.summaryModel')}</div>
          <select className="dropdown">
            <option value="gpt-4">{t('accordion.gpt-4')}</option>
            <option value="model3">{t('accordion.model3')}</option>
            <option value="model4">{t('accordion.model4')}</option>
          </select>
        </div>
      </div>
    </Accordion>
  );
};

export default PreValidatedModelsAccordion;