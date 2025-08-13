import React from 'react';
import notificationi from '../../assets/images/notification.svg';
interface NotificationsDisplayProps {
  notification: string;
}

const NotificationsDisplay: React.FC<NotificationsDisplayProps> = ({ notification }) => {
  return (
    <div className="notifications-display">
      <img src={notificationi} alt="Notification Icon" className="notification-icon" />
      <span>{notification}</span>
    </div>
  );
};

export default NotificationsDisplay;