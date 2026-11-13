import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './styles.css';
import './saas.css';
import './theme-light.css'; // loaded last: light-mode overrides win
import './launch.css'; // approved launch palette + shell refinements
import { initTheme } from './theme.js';

initTheme();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
