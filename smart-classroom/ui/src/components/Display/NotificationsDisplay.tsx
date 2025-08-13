import React from 'react';

interface NotificationsDisplayProps {
  notification: string;
}

const NotificationsDisplay: React.FC<NotificationsDisplayProps> = ({ notification }) => {
  return (
    <div className="notifications-display">
      <span>{notification}</span>
    </div>
  );
};

export default NotificationsDisplay;