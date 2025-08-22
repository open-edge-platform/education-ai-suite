import React, { useState, useRef, useEffect } from 'react';
import Menu from '../Menu/Menu';  
import '../../assets/css/TopPanel.css';
import BrandSlot from '../../assets/images/BrandSlot.svg';
import menu from '../../assets/images/menu.svg';
import { constants } from '../../../public/constants';

interface TopPanelProps {
  projectName: string;
  setProjectName: (name: string) => void;
  isSettingsOpen: boolean;
  setIsSettingsOpen: (isOpen: boolean) => void;
}

const TopPanel: React.FC<TopPanelProps> = ({ projectName, setProjectName, isSettingsOpen, setIsSettingsOpen }) => {
  const [isMenuOpen, setIsMenuOpen] = useState<boolean>(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuIconRef = useRef<HTMLImageElement>(null);

  const toggleMenu = () => {
    setIsMenuOpen(!isMenuOpen);
  };

  const handleClickOutside = (event: MouseEvent) => {
    if (
      menuRef.current &&
      !menuRef.current.contains(event.target as Node) &&
      menuIconRef.current &&
      !menuIconRef.current.contains(event.target as Node)
    ) {
      setIsMenuOpen(false); 
    }
  };

  useEffect(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  return (
    <header className="top-panel">
      <div className="brand-slot">
        <img src={BrandSlot} alt="Intel Logo" className="logo" />
        <span className="app-title">{constants.TITLE}</span>
      </div>
      <div className="action-slot">
        <img
          src={menu}
          alt="Menu Icon"
          className="menu-icon"
          onClick={toggleMenu}
          ref={menuIconRef}
        />
      </div>
      {isMenuOpen && (
        <Menu
          ref={menuRef}
          projectName={projectName}
          setProjectName={setProjectName}
          isSettingsOpen={isSettingsOpen}
          setIsSettingsOpen={setIsSettingsOpen}
        />
      )}
    </header>
  );
};

export default TopPanel;