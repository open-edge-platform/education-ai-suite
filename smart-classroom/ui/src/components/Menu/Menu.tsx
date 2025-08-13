import React, { useState, forwardRef } from 'react';
import Help from './HelpButton';
import About from './AboutButton';
import '../../assets/css/Menu.css';
import SettingsModal from './SettingsButton';

const Menu = forwardRef<HTMLDivElement>((props, ref) => {
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false);

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
      <div className="dropdown-item" onClick={() => handleMenuClick('settings')}>Settings</div>
      <div className="dropdown-item" onClick={() => handleMenuClick('help')}>Help</div>
      <div className="dropdown-item" onClick={() => handleMenuClick('about')}>About</div>
      <div className="menu-content">
        {activeSection === 'help' && <Help />}
        {activeSection === 'about' && <About />}
      </div>
      <SettingsModal isOpen={isSettingsOpen} onClose={closeSettings} />
    </div>
  );
});

export default Menu;