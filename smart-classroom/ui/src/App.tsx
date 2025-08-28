import React, { useState } from 'react';
import TopPanel from './components/TopPanel/TopPanel';
import HeaderBar from './components/Header/Header';
import Body from './components/common/Body';
import Footer from './components/Footer/Footer';
import { constants } from './constants';
import './App.css';

const App: React.FC = () => {
  const [projectName, setProjectName] = useState(constants.PROJECT_NAME);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  return (
    <div className="app">
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