import React, { useState, useEffect } from 'react';
import TopPanel from './components/TopPanel/TopPanel';
import HeaderBar from './components/Header/Header';
import Body from './components/common/Body';
import Footer from './components/Footer/Footer';
import './App.css';
import MetricsPoller from './components/common/MetricsPoller';
import { getSettings } from './services/api';

const App: React.FC = () => {
  const [projectName, setProjectName] = useState<string>(''); 
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  useEffect(() => {
    getSettings()
      .then(s => {
        if (s.projectName) setProjectName(s.projectName);
      })
      .catch(() => {
        console.warn('Failed to fetch project settings');
      });
  }, []);

  return (
    <div className="app">
      <MetricsPoller /> 
      <TopPanel
        projectName={projectName}
        setProjectName={setProjectName}
        isSettingsOpen={isSettingsOpen}
        setIsSettingsOpen={setIsSettingsOpen}
      />
      <HeaderBar projectName={projectName} setProjectName={setProjectName} />
      <div className="main-content">
        <Body isModalOpen={isSettingsOpen} />
      </div>
      <Footer />
    </div>
  );
};

export default App;
