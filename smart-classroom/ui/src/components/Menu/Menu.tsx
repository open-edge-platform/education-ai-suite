import React, { useState, forwardRef } from 'react';
import Help from './HelpButton';
import About from './AboutButton';
import '../../assets/css/Menu.css';
import SettingsModal from './SettingsButton';
import { constants } from '../../constants';
import { useTranslation } from 'react-i18next';
interface MenuProps {
  projectName: string;
  setProjectName: (name: string) => void;
  isSettingsOpen: boolean;
  setIsSettingsOpen: (isOpen: boolean) => void;
}

const Menu = forwardRef<HTMLDivElement, MenuProps>(({ projectName, setProjectName, isSettingsOpen, setIsSettingsOpen }, ref) => {
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const { t } = useTranslation();
  const handleMenuClick = (section: string) => {
    if (section === 'settings') {
      setIsSettingsOpen(true);
    } else {
      setActiveSection(section);
    }
  };

  const closeSettings = () => {
    setIsSettingsOpen(false);
  };

  return (
    <div className="dropdown-menu" ref={ref}>
      <div className="dropdown-item" onClick={() => handleMenuClick('settings')}>{t('menu.settings')}</div>
      <div className="dropdown-item" onClick={() => handleMenuClick('help')}>{t('menu.help')}</div>
      <div className="dropdown-item" onClick={() => handleMenuClick('about')}>{t('menu.about')}</div>
      <div className="menu-content">
        {activeSection === 'help' && <Help />}
        {activeSection === 'about' && <About />}
      </div>
      <SettingsModal isOpen={isSettingsOpen} onClose={closeSettings} projectName={projectName} setProjectName={setProjectName} />
    </div>
  );
});

export default Menu;