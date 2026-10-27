import React, { useRef } from 'react';
import '../../assets/css/TopPanel.css';
import BrandSlot from '../../assets/images/BrandSlot.svg';
import menu from '../../assets/images/settings.svg';
import LanguageSwitcher from '../LanguageSwitcher';
import SettingsModal from '../Menu/SettingsButton';
import { useTranslation } from 'react-i18next';
import type { FeatureGuard } from '../../utils/featureGuards';

interface TopPanelProps {
  projectName: string;
  setProjectName: (name: string) => void;
  isSettingsOpen: boolean;
  setIsSettingsOpen: (isOpen: boolean) => void;
  activeScreen: 'main' | 'content-search' | 'grading';
  setActiveScreen: (screen: 'main' | 'content-search' | 'grading') => void;
  featureGuard: FeatureGuard;
  hasMainFeatures: boolean;
}

const TopPanel: React.FC<TopPanelProps> = ({
  projectName,
  setProjectName,
  isSettingsOpen,
  setIsSettingsOpen,
  activeScreen,
  setActiveScreen,
  featureGuard,
  hasMainFeatures
}) => {
  const menuIconRef = useRef<HTMLImageElement>(null);
  const { t } = useTranslation();

  const openSettings = () => {
    setIsSettingsOpen(true);
  };

  const closeSettings = () => {
    setIsSettingsOpen(false);
  };

  if (activeScreen === 'grading') {
    return (
      <header className="top-panel">
        <div className="brand-slot">
          <img src={BrandSlot} alt="Intel Logo" className="logo" />
          <span className="app-title">{t('grading.title', 'Grading')}</span>
        </div>
        <div className="action-slot">
          <LanguageSwitcher />
        </div>
      </header>
    );
  }

  if (activeScreen === 'content-search') {
    return (
      <header className="top-panel">
        <div className="brand-slot">
          <img src={BrandSlot} alt="Intel Logo" className="logo" />
          <span className="app-title">{t('contentSearch.title', 'Content Search')}</span>
        </div>
        <div className="action-slot">
          <LanguageSwitcher />
        </div>
      </header>
    );
  }

  return (
    <header className="top-panel">
      <div className="brand-slot">
        <img src={BrandSlot} alt="Intel Logo" className="logo" />
        <span className="app-title">{t('header.title')}</span>
      </div>
      <div className="action-slot">
        <LanguageSwitcher />
        <img
          src={menu}
          alt="Menu Icon"
          className="menu-icon"
          onClick={openSettings}
          ref={menuIconRef}
        />
      </div>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={closeSettings}
        projectName={projectName}
        setProjectName={setProjectName}
      />
    </header>
  );
};

export default TopPanel;
