import React from 'react';
import TopPanel from './components/TopPanel/TopPanel';
import HeaderBar from './components/Header/Header'; // Example additional component
import './App.css';

const App: React.FC = () => {
  return (
    <div className="app">
      <TopPanel />
      <HeaderBar />
      {/* Other components or routes go here */}
    </div>
  );
};

export default App;