import React, { useState } from "react";
import "../../assets/css/Accordion.css"; 
interface AccordionProps {
  title: string;
  children: React.ReactNode;
}

const Accordion: React.FC<AccordionProps> = ({ title, children }) => {
  const [isOpen, setIsOpen] = useState(false);

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };

  return (
    <div className="accordion">
      <div className="accordion-header" onClick={toggleAccordion}>
        <h3>{title}</h3>
        <span>{isOpen ? "-" : "+"}</span>
      </div>
      {isOpen && <div className="accordion-content">{children}</div>}
    </div>
  );
};

export default Accordion;