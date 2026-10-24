import React from 'react';
import { useNavigate } from 'react-router-dom';
import Tabs from '../ui/Tabs';
import { HANDBOOK_TABS } from '../../utils/handbook';

/** The handbook's sections (Future lives under Lab › Backlog). */
const SystemTabs = ({ active, onSelect }) => {
  const navigate = useNavigate();
  const select = (id) => {
    if (onSelect) onSelect(id);
    else navigate(id === 'system' ? '/lab/handbook' : `/lab/handbook?tab=${id}`);
  };
  return <Tabs tabs={HANDBOOK_TABS} value={active} onChange={select} label="Handbook" />;
};

export default SystemTabs;
