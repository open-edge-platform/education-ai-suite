import React from 'react';
import TopPanel from './components/TopPanel/TopPanel';
import HeaderBar from './components/Header/Header';
import './App.css';

const App: React.FC = () => {
  return (
    <div className="app">
      <TopPanel />
      <HeaderBar />
    </div>
  );
};

export default App;