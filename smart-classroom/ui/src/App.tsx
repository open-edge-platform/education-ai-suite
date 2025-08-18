import React, { useState } from 'react';
import TopPanel from './components/TopPanel/TopPanel';
import HeaderBar from './components/Header/Header';
import './App.css';
import { constants } from '../public/constants';

const App: React.FC = () => {
  const [projectName, setProjectName] = useState(constants.PROJECT_NAME);

  return (
    <div className="app">
      <TopPanel projectName={projectName} setProjectName={setProjectName} />
      <HeaderBar projectName={projectName} setProjectName={setProjectName} />
    </div>
  );
};

export default App;