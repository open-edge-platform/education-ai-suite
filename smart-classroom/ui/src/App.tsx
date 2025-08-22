import React, { useState } from 'react';
import TopPanel from './components/TopPanel/TopPanel';
import HeaderBar from './components/Header/Header';
import Body from './components/common/Body';
import { constants } from '../public/constants';
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
      <Body isModalOpen={isSettingsOpen} />
    </div>
  );
};

export default App;