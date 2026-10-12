import React from 'react';
import ReactDOM from 'react-dom/client';
import DMSAIChat from '../DMSAIChat (1).jsx';

const mockUser = {
  userid: 'preview-user-001',
  firstName: 'Demo User',
  email: 'demo@eazydms.com',
  'X-UID': 'preview-session-abc',
  'X-Staff-UID': 'preview-user-001',
  'U-UID': 'preview-user-001',
  'x-bypass-uid': 'true',
  dmsAiBaseUrl: 'https://chatbotuatnew.eazydms.com',
};

function PreviewApp() {
  return (
    <div className="preview-shell">
      <div className="preview-banner">
        <span className="preview-badge">PREVIEW</span>
        <strong>DMSAIChat (1).jsx</strong>
        <span>— Fully rendered live React component with interactive mock API</span>
      </div>
      <div className="preview-component-wrap">
        <DMSAIChat isMaximized={true} user={mockUser} />
      </div>
    </div>
  );
}

const container = document.getElementById('root');
const root = ReactDOM.createRoot(container);
root.render(<PreviewApp />);
