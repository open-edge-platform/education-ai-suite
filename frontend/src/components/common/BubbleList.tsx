import React from "react";
import "./BubbleList.scss";

interface BubbleItemProps {
  text: string;
  timestamp?: string;
  speaker?: string;
}

interface BubbleListProps {
  items: BubbleItemProps[];
}

const BubbleItem = ({ text, timestamp, speaker }: BubbleItemProps) => {
  return (
    <div className="bubble-item" role="listitem">
      {timestamp && <span className="timestamp">{timestamp}</span>}
      {speaker && <span className="speaker">{speaker}: </span>}
      <span className="text">{text}</span>
    </div>
  );
};

const BubbleList = ({ items }: BubbleListProps) => {
  return (
    <div className="bubble-list" role="list">
      {items.map((item, index) => (
        <BubbleItem key={index} {...item} />
      ))}
    </div>
  );
};

export default BubbleList;