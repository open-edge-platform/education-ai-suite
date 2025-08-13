import React, { useState, useEffect, useRef } from 'react';
import Menu from '../Menu/Menu';  
import '../../assets/css/TopPanel.css';
const TopPanel: React.FC = () => {
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
      console.log('Clicked outside the menu');
      setIsMenuOpen(false); // Close the menu when clicking outside
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
        <img src="src/assets/images/BrandSlot.svg" alt="Intel Logo" className="logo" />
        <span className="app-title">Smart Classroom Sample App</span>
      </div>
      <div className="action-slot">
        <img
          src="src/assets/images/menu.svg"
          alt="Menu Icon"
          className="menu-icon"
          onClick={toggleMenu}
          ref={menuIconRef}
        />
      </div>
      {isMenuOpen && <Menu ref={menuRef} />}
    </header>
  );
};

export default TopPanel;