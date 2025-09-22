import React from 'react';
import notificationicon from '../../assets/images/notification.svg';

interface NotificationsDisplayProps {
  notification: string;
  error?: string | null; 
}

const NotificationsDisplay: React.FC<NotificationsDisplayProps> = ({ notification, error }) => {
  return (
    <div className={`notifications-display ${error ? 'has-error' : ''}`}>
      <img
        src={notificationicon}
        alt="Notification Icon"
        className="notification-icon"
        style={error ? { filter: 'hue-rotate(330deg) saturate(3)', opacity: 0.9 } : {}}
      />
      <span style={error ? { color: '#c62828', fontWeight: 600 } : {}}>
        {error || notification}
      </span>
    </div>
  );
};

export default NotificationsDisplay;