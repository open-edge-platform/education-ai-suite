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
          </select>
        </div>
        <div className="dropdown-section">
          <div className="accordion-content">{t('accordion.summaryModel')}</div>
          <select className="dropdown">
            <option value="gpt-4">{t('accordion.gpt-4')}</option>
          </select>
        </div>
      </div>
    </Accordion>
  );
};

export default PreValidatedModelsAccordion;