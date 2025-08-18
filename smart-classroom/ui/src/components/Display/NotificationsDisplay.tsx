import React from 'react';
import notificationicon from '../../assets/images/notification.svg';
interface NotificationsDisplayProps {
  notification: string;
}

const NotificationsDisplay: React.FC<NotificationsDisplayProps> = ({ notification }) => {
  return (
    <div className="notifications-display">
      <img src={notificationicon} alt="Notification Icon" className="notification-icon" />
      <span>{notification}</span>
    </div>
  );
};

export default NotificationsDisplay;